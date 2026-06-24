# app/core/security.py
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from app.core.config import settings

_ACCESS_AUD = "geo-map-access"
_REFRESH_AUD = "geo-map-refresh"


# ── Access token ──────────────────────────────────────────────────────────────


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
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
        # Reject if type claim is missing or not "access" — prevent
        # refresh tokens from being used as access tokens.
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


# ── Refresh token ─────────────────────────────────────────────────────────────


def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
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
