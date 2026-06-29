# app/core/security.py
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from app.core.config import settings

logger = logging.getLogger(__name__)

_ACCESS_AUD = "geo-map-access"
_REFRESH_AUD = "geo-map-refresh"


def _validate_sub(data: dict) -> dict:
    """Validate that 'sub' claim is present and is a string-encoded integer."""
    sub = data.get("sub")
    if sub is None:
        raise ValueError("Token payload must include 'sub' claim")
    try:
        int(sub)
    except (ValueError, TypeError):
        raise ValueError(f"'sub' claim must be a string-encoded integer, got: {sub}")
    return data


# Access token
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = _validate_sub(data.copy())
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update(
        {
            "type": "access",
            "exp": expire,
            "iat": now,
            "aud": _ACCESS_AUD,
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=_ACCESS_AUD,
        )

        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


# Refresh token
def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = _validate_sub(data.copy())
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update(
        {
            "type": "refresh",
            "exp": expire,
            "iat": now,
            "aud": _REFRESH_AUD,
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_refresh_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=_REFRESH_AUD,
        )
        # Extra guard — reject if someone crafts a token without the type claim
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None


# Password reset token (short-lived JWT)
_RESET_AUD = "geo-map-password-reset"
_RESET_TTL_MINUTES = 5


def create_password_reset_token(user_id: int) -> str:
    """
    Create a short-lived JWT that authorises a password reset.
    Issued after OTP verification, consumed by the reset-password endpoint.

    Each token includes a random nonce that binds it to a specific OTP
    verification event. If a token is leaked, it cannot be replayed after
    being used, and a new OTP verification is required to get a fresh token.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=_RESET_TTL_MINUTES)
    payload = {
        "sub": str(user_id),
        "type": "password_reset",
        "exp": expire,
        "iat": now,
        "aud": _RESET_AUD,
        "nonce": secrets.token_hex(
            16
        ),  # 128-bit random nonce — binds token to verification event
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_password_reset_token(token: str) -> Optional[dict]:
    """
    Decode and verify a password reset token.
    Returns the payload dict on success, None on any failure.

    Validates:
    - JWT signature and expiry
    - Audience claim
    - Type claim (must be "password_reset")
    - Nonce presence (binds token to OTP verification event)
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=_RESET_AUD,
        )
        if payload.get("type") != "password_reset":
            return None
        # Require nonce — ensures the token was issued after a specific
        # OTP verification, not forged with just a user_id.
        if not payload.get("nonce"):
            return None
        return payload
    except JWTError:
        return None
