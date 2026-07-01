# app/dependencies/auth.py

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth_utils import validate_token_sub
from app.core.security import decode_access_token
from app.database.connection import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.token_blacklist_service import TokenBlacklistService

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()
# auto_error=False so public endpoints can receive an optional token
bearer_scheme_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Redis blacklist check — tokens revoked via /auth/logout or /auth/refresh
    is_blacklisted = await TokenBlacklistService.is_token_blacklisted(token)
    if is_blacklisted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify HS256 signature + expiry
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id_str: Optional[str] = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    user_id = validate_token_sub(user_id_str)
    if user_id is None:
        raise credentials_exception

    # Load from PostgreSQL
    repo = UserRepository(db)
    user = repo.get_active_by_id(user_id)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Please contact support.",
        )

    # Password-changed-at check — invalidates all tokens issued before the
    # last password change or reset. Ensures that a stolen token cannot be
    # used after the user has changed their password.
    if user.password_changed_at is not None:
        token_iat = payload.get("iat")
        if token_iat is not None:
            # token_iat is a Unix timestamp (int), password_changed_at is a datetime
            changed_at_ts = user.password_changed_at.timestamp()
            if token_iat < changed_at_ts:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked due to password change. Please log in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    return user


async def get_current_verified_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Email address not verified. "
                "Please verify your email before accessing this resource."
            ),
        )
    return current_user


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Returns the authenticated User if a valid Bearer token is present in the
    request, or None if no Authorization header was sent.

    Used on public endpoints (signup, login) to detect callers who are already
    logged in — without making authentication mandatory.
    """
    if credentials is None:
        return None

    token = credentials.credentials

    # Reject blacklisted tokens so a logged-out token cannot be replayed
    try:
        is_blacklisted = await TokenBlacklistService.is_token_blacklisted(token)
        if is_blacklisted:
            return None
    except Exception:
        # If Redis is unavailable we simply treat the token as absent
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id = validate_token_sub(payload.get("sub"))
    if user_id is None:
        return None

    repo = UserRepository(db)
    user = repo.get_active_by_id(user_id)
    if user is None or not user.is_active:
        return None

    # Honour password-changed-at invalidation
    if user.password_changed_at is not None:
        token_iat = payload.get("iat")
        if token_iat is not None and token_iat < user.password_changed_at.timestamp():
            return None

    return user
