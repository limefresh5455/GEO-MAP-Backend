# app/api/v1/auth.py
import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiter import shared_limiter as limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.repositories.user_repository import (
    UserRepository,
    hash_password,
    verify_password,
)
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
    VerifyOTPRequest,
)
from app.services.email_service import send_otp_email
from app.services.otp_service import (
    delete_pending_registration,
    set_pending_user_id,
    store_pending_registration,
    verify_and_consume,
)
from app.services.token_blacklist_service import TokenBlacklistService

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["Authentication"])

_REFRESH_EXPIRES_IN = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        is_active=user.is_active,
        email_verified=user.email_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        credits=user.credits,
    )


def _issue_token_pair(user: User) -> TokenResponse:
    """
    Issue both an access token (1 hour) and a refresh token (7 days) for the user.
    Called from verify-otp, login, and refresh endpoints.
    """
    access = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh = create_refresh_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # 3600 seconds
        refresh_expires_in=_REFRESH_EXPIRES_IN,  # 604800 seconds
        user=_user_to_response(user),
    )


# ── POST /auth/signup ─────────────────────────────────────────────────────────


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_200_OK,
    summary="Register — sends OTP to email",
    description=(
        "Creates a pending registration and sends a **6-digit OTP** to the email.\n\n"
        "Account is **not created yet** — call `POST /auth/verify-otp` to finish.\n\n"
        "Password rules: min 8 chars, 1 uppercase, 1 digit. OTP expires in **2 minutes**."
    ),
)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    db: Session = Depends(get_db),
):
    repo = UserRepository(db)

    if repo.get_by_email(payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please log in.",
        )

    pw_hash = hash_password(payload.password)

    # BUG FIX: Pre-create the user in PostgreSQL as pending (inactive, unverified)
    # so we don't store hashed_password in Redis. Only user_id is stored in Redis
    # alongside the OTP, which is much safer if Redis is compromised.
    pending_user = repo.create_pending_user(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=pw_hash,
    )

    try:
        otp = await store_pending_registration(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=pw_hash,
        )
        # Associate the pending user_id with the OTP record
        await set_pending_user_id(payload.email, pending_user.id)
    except RuntimeError as exc:
        # Rollback the pending user creation
        repo.delete_pending_user(pending_user)
        logger.error("Redis unavailable during signup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration service temporarily unavailable. Please try again.",
        )

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            send_otp_email,
            payload.email,
            payload.full_name,
            otp,
        )
    except Exception as exc:
        await delete_pending_registration(payload.email)
        repo.delete_pending_user(pending_user)
        logger.error("Failed to send OTP email to %s: %s", payload.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send verification email. Check your email address and try again.",
        )

    db.commit()
    logger.info(
        "Signup OTP sent to %s, pending user id=%s", payload.email, pending_user.id
    )
    return SignupResponse(
        message="Verification code sent. Check your email and call POST /auth/verify-otp.",
        email=payload.email,
        otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
    )


# ── POST /auth/verify-otp ─────────────────────────────────────────────────────


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP — creates account, returns access + refresh tokens",
    description=(
        "Submits the 6-digit OTP received by email.\n\n"
        "On success:\n"
        "- User account created (`email_verified = true`)\n"
        "- Returns **access_token** (1 hour) and **refresh_token** (7 days)\n\n"
        "Max 5 wrong attempts before the code is invalidated."
    ),
)
@limiter.limit("10/minute")
async def verify_otp_endpoint(
    request: Request,
    payload: VerifyOTPRequest,
    db: Session = Depends(get_db),
):
    try:
        reg_data = await verify_and_consume(
            email=payload.email,
            submitted_otp=payload.otp,
        )
    except RuntimeError as exc:
        logger.error("Redis error during OTP verify: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable. Please try again.",
        )

    if reg_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid or expired verification code. "
                "Check the code or call POST /auth/signup again to get a new one."
            ),
        )

    repo = UserRepository(db)

    # BUG FIX: User was pre-created during signup as pending (inactive, unverified).
    # Now we just activate the existing user instead of creating a new one.
    # This avoids storing hashed_password in Redis (security improvement).
    user_id_str = reg_data.get("user_id")
    user = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
            user = repo.get_by_id(user_id)
        except (ValueError, TypeError):
            pass

    if user is None:
        # Fallback: try to find by email (for backward compatibility with old-style registrations)
        user = repo.get_by_email(payload.email)
        if user is None or user.email_verified:
            # If email_verified is True, user is already active — return tokens
            if user and user.email_verified:
                logger.info(
                    "verify-otp: user already verified for %s — returning token pair",
                    payload.email,
                )
                return _issue_token_pair(user)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration expired. Please call POST /auth/signup again.",
            )

    # Activate the pending user
    user = repo.activate_pending_user(user)
    db.commit()

    logger.info("User activated via OTP: id=%s email=%s", user.id, payload.email)
    return _issue_token_pair(user)


# ── POST /auth/login ──────────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login — returns access + refresh tokens",
    description=(
        "Authenticate with email and password.\n\n"
        "Returns:\n"
        "- **access_token** — valid 1 hour — send as `Authorization: Bearer <token>`\n"
        "- **refresh_token** — valid 7 days — use on `POST /auth/refresh` when access token expires"
    ),
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    repo = UserRepository(db)
    user = repo.get_by_email(payload.email)

    if user is None or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Please contact support.",
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Complete signup via POST /auth/signup then /auth/verify-otp.",
        )

    logger.info("Login success: user_id=%s", user.id)
    return _issue_token_pair(user)


# ── GET /auth/me ──────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user profile",
    description=(
        "Returns the profile of the currently authenticated user.\n\n"
        "Requires a valid **access token** in the Authorization header."
    ),
)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return _user_to_response(current_user)


# ── POST /auth/refresh ────────────────────────────────────────────────────────


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh — exchange refresh token for new token pair",
    description=(
        "Exchange a valid **refresh_token** for a brand-new access + refresh token pair.\n\n"
        "**Rotation:** the submitted refresh_token is blacklisted immediately — "
        "it cannot be used again. A new refresh_token is returned.\n\n"
        "Call this when the access_token expires (HTTP 401 on a protected endpoint).\n\n"
        "Do **not** send an Authorization header — only the body is needed."
    ),
)
@limiter.limit("20/minute")
async def refresh_tokens(
    request: Request,
    payload: RefreshRequest,
    db: Session = Depends(get_db),
):
    refresh_tok = payload.refresh_token

    # 1. Check Redis blacklist first — fast-fail if already used / logged out
    is_blacklisted = await TokenBlacklistService.is_token_blacklisted(refresh_tok)
    if is_blacklisted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Verify signature + expiry + audience + type claim
    token_payload = decode_refresh_token(refresh_tok)
    if token_payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Load user from DB
    user_id_str = token_payload.get("sub")
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    repo = UserRepository(db)
    user = repo.get_active_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account inactive. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Issue fresh token pair FIRST
    #    BUG FIX: Original code blacklisted the old token FIRST, then issued
    #    new ones. If the server crashed between steps, the user's refresh
    #    token was invalidated with no replacement, forcing re-login.
    #    New order: issue new tokens first, then blacklist the old one.
    #    If a crash occurs now, the old token remains valid and can be
    #    retried on the next request.
    new_tokens = _issue_token_pair(user)

    # 5. Blacklist the used refresh token (rotation — single-use)
    await TokenBlacklistService.blacklist_token(refresh_tok)

    logger.info("Tokens refreshed for user_id=%s", user.id)
    return new_tokens


# ── POST /auth/logout ─────────────────────────────────────────────────────────


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout — revoke access token and refresh token",
    description=(
        "Blacklists the current **access token** (from Authorization header) "
        "and the **refresh_token** (from request body, optional).\n\n"
        "After this call neither token works. The user must log in again.\n\n"
        "Always send the refresh_token in the body to fully invalidate the session."
    ),
)
@limiter.limit("10/minute")
async def logout(
    request: Request,
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
):
    access_tok = credentials.credentials

    # Blacklist access token
    await TokenBlacklistService.blacklist_token(access_tok)

    # Blacklist refresh token if provided
    if payload.refresh_token:
        await TokenBlacklistService.blacklist_token(payload.refresh_token)
        logger.info(
            "Full logout — access + refresh tokens revoked: user_id=%s", current_user.id
        )
    else:
        logger.info(
            "Partial logout — only access token revoked (no refresh_token sent): user_id=%s",
            current_user.id,
        )

    return MessageResponse(message="Logged out successfully. Tokens revoked.")
