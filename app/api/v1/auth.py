# app/api/v1/auth.py
import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiter import shared_limiter as limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    decode_password_reset_token,
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
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    ResendOTPRequest,
    ResendOTPResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
    VerificationStatusResponse,
    VerifyOTPRequest,
    VerifyResetOTPRequest,
    VerifyResetOTPResponse,
)
from app.services.email_service import send_otp_email, send_reset_email
from app.services.otp_service import (
    delete_pending_registration,
    delete_reset_otp,
    set_pending_user_id,
    store_pending_registration,
    store_reset_otp,
    verify_and_consume,
    verify_reset_otp,
)
from app.services.token_blacklist_service import TokenBlacklistService

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["Authentication"])

_REFRESH_EXPIRES_IN = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # seconds

# Helpers
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
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=_REFRESH_EXPIRES_IN,
        user=_user_to_response(user),
    )


# POST /auth/signup
@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_200_OK,
    summary="Register — sends OTP to email",
    description=(
        "Creates a pending registration and sends a 6-digit OTP to the email. "
        "Account is not created yet - call verify-otp to finish. "
        "Password rules: minimum 8 characters, 1 uppercase letter, 1 digit, "
        "1 lowercase letter, and 1 special character. OTP expires in 2 minutes."
    ),
)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    db: Session = Depends(get_db),
):
    repo = UserRepository(db)

    existing_user = repo.get_by_email(payload.email)
    if existing_user is not None:
        # ── Pending user (never verified OTP) → allow re-registration ──
        if not existing_user.email_verified:
            logger.info(
                "Re-registration for pending email %s — deleting old pending user",
                payload.email,
            )
            # Also clean up any stale OTP in Redis
            await delete_pending_registration(payload.email)
            repo.delete_pending_user(existing_user)
            db.flush()
        else:
            # Fully registered user — return generic success to prevent enumeration
            logger.info(
                "Signup blocked for existing verified email: %s — returning generic success",
                payload.email,
            )
            return SignupResponse(
                message="If an account with this email exists, a verification code has been sent.",
                email=payload.email,
                otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
            )

    pw_hash = hash_password(payload.password)

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
        await set_pending_user_id(payload.email, pending_user.id)
    except RuntimeError as exc:
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
        message="Verification code sent. Check your email and enter the code to complete registration.",
        email=payload.email,
        otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
    )


# POST /auth/verify-otp
@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP — creates account, returns access + refresh tokens",
    description=(
        "Submits the 6-digit OTP received by email. "
        "On success: User account is activated. Returns an access token "
        "(valid 1 hour) and a refresh token (valid 7 days). "
        "Maximum 5 wrong attempts before the code is invalidated."
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
                "Check the code or sign up again to get a new one."
            ),
        )

    repo = UserRepository(db)

    user_id_str = reg_data.get("user_id")
    user = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
            user = repo.get_by_id(user_id)
        except (ValueError, TypeError):
            pass

    if user is None:
        user = repo.get_by_email(payload.email)
        if user is None or user.email_verified:
            if user and user.email_verified:
                logger.info(
                    "verify-otp: user already verified for %s — rejecting OTP consumption",
                    payload.email,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Account already verified. Please log in.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration expired. Please sign up again.",
            )

    # Activate the pending user
    user = repo.activate_pending_user(user)
    db.commit()

    logger.info("User activated via OTP: id=%s email=%s", user.id, payload.email)
    return _issue_token_pair(user)


# POST /auth/login
@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login — returns access + refresh tokens",
    description=(
        "Authenticate with email and password. "
        "Returns an access token (valid 1 hour) and a refresh token (valid 7 days)."
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
            detail=(
                "Email not verified. "
                "Check your verification status to see if you need to resend "
                "the verification code and complete verification."
            ),
        )

    logger.info("Login success: user_id=%s", user.id)
    return _issue_token_pair(user)


# GET /auth/me
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


# POST /auth/refresh
@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh — exchange refresh token for new token pair",
    description=(
        "Exchange a valid refresh token for a brand-new access and refresh token pair. "
        "The submitted refresh token is blacklisted immediately - it cannot be used again. "
        "A new refresh token is returned. "
        "Call this when the access token expires (HTTP 401 on a protected endpoint). "
        "Do not send an Authorization header - only the body is needed."
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

    # Password-changed-at check — reject refresh tokens issued before the
    # last password change or reset.
    token_iat = token_payload.get("iat")
    if user.password_changed_at is not None and token_iat is not None:
        changed_at_ts = user.password_changed_at.timestamp()
        if token_iat < changed_at_ts:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked due to password change. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    new_tokens = _issue_token_pair(user)

    # 5. Blacklist the used refresh token (rotation — single-use)
    await TokenBlacklistService.blacklist_token(refresh_tok)

    logger.info("Tokens refreshed for user_id=%s", user.id)
    return new_tokens


# POST /auth/logout
@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout — revoke access token and refresh token",
    description=(
        "Blacklists the current access token (from Authorization header) "
        "and the refresh token (from request body, optional). "
        "After this call neither token works. The user must log in again. "
        "Always send the refresh token in the body to fully invalidate the session."
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


# POST /auth/resend-otp
@router.post(
    "/resend-otp",
    response_model=ResendOTPResponse,
    status_code=status.HTTP_200_OK,
    summary="Resend OTP — sends a fresh verification code to email",
    description=(
        "Resends a new 6-digit OTP to the email address if there is a pending "
        "(unverified) registration for that email. "
        "Use this when the original OTP has expired or the user did not receive it. "
        "New OTP expires in 2 minutes. Rate-limited to 3 requests per minute."
    ),
)
@limiter.limit("3/minute")
@limiter.limit("10/hour")
async def resend_otp(
    request: Request,
    payload: ResendOTPRequest,
    db: Session = Depends(get_db),
):
    repo = UserRepository(db)
    user = repo.get_by_email(payload.email)

    # ── Don't reveal whether the email exists or is verified (prevent enumeration) ──
    if user is None or user.email_verified:
        if user is None:
            logger.info(
                "Resend-OTP requested for non-existent email: %s — returning generic success",
                payload.email,
            )
        else:
            logger.info(
                "Resend-OTP requested for already-verified email: %s — returning generic success",
                payload.email,
            )
        return ResendOTPResponse(
            message="If a pending account with this email exists, a new verification code has been sent.",
            email=payload.email,
            otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
        )

    # ── Generate new OTP ──
    pw_hash = user.hashed_password
    try:
        otp = await store_pending_registration(
            email=payload.email,
            full_name=user.full_name,
            hashed_password=pw_hash,
        )
        await set_pending_user_id(payload.email, user.id)
    except RuntimeError as exc:
        logger.error("Redis unavailable during resend-otp: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable. Please try again.",
        )

    # ── Send email ──
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            send_otp_email,
            payload.email,
            user.full_name,
            otp,
        )
    except Exception as exc:
        await delete_pending_registration(payload.email)
        logger.error("Failed to resend OTP email to %s: %s", payload.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send verification email. Check your email address and try again.",
        )

    logger.info("OTP resent to %s (pending user id=%s)", payload.email, user.id)
    return ResendOTPResponse(
        message="A new verification code has been sent to your email.",
        email=payload.email,
        otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
    )


# GET /auth/verification-status
@router.get(
    "/verification-status",
    response_model=VerificationStatusResponse,
    summary="Check account verification status",
    description=(
        "Returns whether an email is registered and whether the user has "
        "completed OTP verification. "
        "Use this endpoint to show the correct next step to the user. "
        "No authentication required."
    ),
)
@limiter.limit("30/minute")
async def verification_status(
    request: Request,
    email: str = Query(
        ...,
        min_length=3,
        max_length=255,
        description="Email address to check",
    ),
    db: Session = Depends(get_db),
) -> VerificationStatusResponse:
    repo = UserRepository(db)
    user = repo.get_by_email(email)

    if user is None:
        return VerificationStatusResponse(
            registered=False,
            email_verified=False,
            is_pending=False,
            message="No account found with this email. Please sign up first.",
        )

    if user.email_verified:
        return VerificationStatusResponse(
            registered=True,
            email_verified=True,
            is_pending=False,
            message="Your email is verified. You can log in.",
        )

    # Pending — registered but not verified
    return VerificationStatusResponse(
        registered=True,
        email_verified=False,
        is_pending=True,
        message=(
            "You have signed up but have not verified your email yet. "
            "Check your inbox for the OTP and enter it to complete registration. "
            "If the OTP expired, request a new one."
        ),
    )


# ── POST /auth/forgot-password ─────────────────────────────────────────────────


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset — sends OTP to email",
    description=(
        "Initiates a password reset for an existing, verified account. "
        "A 6-digit OTP is sent to the registered email address. "
        "The OTP expires in 5 minutes. "
        "After verifying the OTP via /auth/verify-reset-otp, use the returned "
        "reset_token to call /auth/reset-password."
    ),
)
@limiter.limit("3/minute")
@limiter.limit("10/hour")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    repo = UserRepository(db)
    user = repo.get_by_email(payload.email)

    # ── Don't reveal whether the email exists (prevent enumeration) ──
    if user is None:
        logger.info(
            "Forgot-password requested for non-existent email: %s — returning generic success",
            payload.email,
        )
        return ForgotPasswordResponse(
            message="If an account with this email exists, a password reset code has been sent.",
            email=payload.email,
            otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
        )

    # ── User must be verified to reset password ──
    if not user.email_verified:
        logger.info(
            "Forgot-password blocked for unverified email: %s",
            payload.email,
        )
        # Still return generic success to avoid enumeration
        return ForgotPasswordResponse(
            message="If an account with this email exists, a password reset code has been sent.",
            email=payload.email,
            otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
        )

    # ── Inactive account ──
    if not user.is_active:
        logger.info(
            "Forgot-password blocked for inactive account: %s",
            payload.email,
        )
        return ForgotPasswordResponse(
            message="If an account with this email exists, a password reset code has been sent.",
            email=payload.email,
            otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
        )

    # ── Generate and store reset OTP ──
    try:
        otp = await store_reset_otp(
            email=payload.email,
            user_id=user.id,
        )
    except RuntimeError as exc:
        logger.error("Redis unavailable during forgot-password: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset service temporarily unavailable. Please try again.",
        )

    # ── Send email ──
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            send_reset_email,
            payload.email,
            user.full_name,
            otp,
        )
    except Exception as exc:
        await delete_reset_otp(payload.email)
        logger.error(
            "Failed to send password reset email to %s: %s", payload.email, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send password reset email. Check your email address and try again.",
        )

    logger.info("Password reset OTP sent to %s (user_id=%s)", payload.email, user.id)
    return ForgotPasswordResponse(
        message="If an account with this email exists, a password reset code has been sent.",
        email=payload.email,
        otp_expires_in_seconds=settings.OTP_EXPIRE_SECONDS,
    )


# ── POST /auth/verify-reset-otp ───────────────────────────────────────────────


@router.post(
    "/verify-reset-otp",
    response_model=VerifyResetOTPResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify password reset OTP — returns reset token",
    description=(
        "Verifies the 6-digit OTP sent to the user's email during password reset. "
        "On success, returns a short-lived reset_token (valid 5 minutes) that must be "
        "sent via the X-Reset-Token header to /auth/reset-password. "
        "Maximum 5 wrong attempts before the code is invalidated."
    ),
)
@limiter.limit("10/minute")
async def verify_reset_otp_endpoint(
    request: Request,
    payload: VerifyResetOTPRequest,
    db: Session = Depends(get_db),
):
    try:
        reg_data = await verify_reset_otp(
            email=payload.email,
            submitted_otp=payload.otp,
        )
    except RuntimeError as exc:
        logger.error("Redis error during reset OTP verify: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable. Please try again.",
        )

    if reg_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid or expired verification code. "
                "Request a new code via /auth/forgot-password."
            ),
        )

    # Extract user_id and validate user still exists
    user_id_str = reg_data.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification data is incomplete. Please request a new code.",
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification data. Please request a new code.",
        )

    repo = UserRepository(db)
    user = repo.get_active_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account no longer exists or has been deactivated.",
        )

    # Generate short-lived reset token
    reset_token = create_password_reset_token(user_id=user.id)

    logger.info("Reset OTP verified for user_id=%s — reset token issued", user.id)

    return VerifyResetOTPResponse(
        message="Verification successful. You can now reset your password.",
        reset_token=reset_token,
        expires_in=300,  # 5 minutes
    )


# ── POST /auth/reset-password ──────────────────────────────────────────────────


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password using reset token",
    description=(
        "Set a new password using a verified reset token (obtained from "
        "/auth/verify-reset-otp). The reset token must be sent in the "
        "X-Reset-Token header. "
        "After successful reset, the user must log in again with their new password."
    ),
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    # ── Extract reset token from header or body (fallback) ──
    reset_token = request.headers.get("X-Reset-Token") or payload.reset_token
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing reset token. Provide X-Reset-Token header or reset_token in body.",
        )

    # ── Validate reset token ──
    token_payload = decode_password_reset_token(reset_token.strip())
    if token_payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token. Please request a new code.",
        )

    user_id_str = token_payload.get("sub")
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid reset token payload.",
        )

    # ── Load user ──
    repo = UserRepository(db)
    user = repo.get_active_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found or inactive.",
        )

    # ── Validate and hash new password ──
    new_hashed = hash_password(payload.new_password)

    # ── Update password in DB ──
    repo.update_password(user, new_hashed)
    db.commit()

    # Note: We can't enumerate all user's tokens to blacklist them individually.
    # Existing tokens remain valid until natural expiry (access: 1h, refresh: 7d).
    # The user is directed to log in again with the new password.

    logger.info(
        "Password reset successful for user_id=%s",
        user.id,
    )

    return ResetPasswordResponse(
        message="Password reset successful. Please log in with your new password.",
    )


# ── POST /auth/change-password ────────────────────────────────────────────────


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Change password (authenticated)",
    description=(
        "Allows an authenticated user to change their password. "
        "The current password must be provided for verification. "
        "After a successful change, the current access token is revoked "
        "and the user must log in again with the new password."
    ),
)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: Session = Depends(get_db),
):
    # ── Verify old password ──
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    # ── Hash and update new password ──
    new_hashed = hash_password(payload.new_password)
    repo = UserRepository(db)
    repo.update_password(current_user, new_hashed)
    db.commit()

    # ── Blacklist the current access token (rotate session) ──
    await TokenBlacklistService.blacklist_token(credentials.credentials)

    # ── Blacklist the refresh token if provided (full session logout) ──
    if payload.refresh_token:
        await TokenBlacklistService.blacklist_token(payload.refresh_token)

    logger.info(
        "Password changed successfully for user_id=%s — access token revoked"
        + (" and refresh token revoked" if payload.refresh_token else ""),
        current_user.id,
    )

    return ChangePasswordResponse(
        message="Password changed successfully. Please log in again.",
    )
