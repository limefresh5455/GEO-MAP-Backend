from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt hard limit — passwords longer than 72 bytes are truncated by the algorithm.
# We enforce this explicitly so behaviour is predictable.
_BCRYPT_MAX_BYTES = 72

# B-010 FIX: Increase bcrypt work factor from default 12 to 14 rounds
# Modern hardware can compute 12 rounds in <50ms, 14 rounds takes ~200ms (more secure)
_BCRYPT_ROUNDS = 14

# B-008 FIX: JWT audience claim for cross-service protection
_JWT_AUDIENCE = "geo-map-backend"

# B06: Pre-computed hash used for constant-time dummy verification on login.
# The plaintext is arbitrary — it is never used for authentication.
DUMMY_HASH: str = bcrypt.hashpw(
    b"__dummy_constant_time__", 
    bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
).decode("utf-8")


def _encode(password: str) -> bytes:
    encoded = password.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """
    Hash a plain-text password with bcrypt. Returns a utf-8 string.
    B-010 FIX: Uses 14 rounds for enhanced security.
    """
    hashed = bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its bcrypt hash."""
    return bcrypt.checkpw(_encode(plain_password), hashed_password.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "aud": _JWT_AUDIENCE,  # B-008 FIX
        "iat": datetime.now(timezone.utc),  # issued at
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token. Returns payload dict or None.
    B-008 FIX: Validates audience claim.
    """
    try:
        return jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM],
            audience=_JWT_AUDIENCE  # B-008 FIX
        )
    except JWTError:
        return None
