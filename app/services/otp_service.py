# app/services/otp_service.py
import json
import logging
import secrets
import string

from app.core.config import settings
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

_PENDING_PREFIX = "otp:pending:"

_VERIFY_LUA_SCRIPT = """
local key     = KEYS[1]
local otp_in  = ARGV[1]
local max_att = tonumber(ARGV[2])

local raw = redis.call('GET', key)
if not raw then
    return {3, ''}
end

local data = cjson.decode(raw)
if data['otp'] == otp_in then
    -- Correct OTP — consume and return the user_id
    redis.call('DEL', key)
    return {0, data['user_id']}
end

-- Wrong OTP
local attempts = (data['attempts'] or 0) + 1
if attempts >= max_att then
    redis.call('DEL', key)
    return {1, ''}
end

data['attempts'] = attempts
local ttl = redis.call('TTL', key)
if ttl > 0 then
    redis.call('SETEX', key, ttl, cjson.encode(data))
end
return {2, tostring(attempts)}
"""

def _generate_otp(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


async def store_pending_registration(
    email: str,
    full_name: str,
    hashed_password: str,
) -> str:
    redis = get_redis_client()
    if redis is None:
        raise RuntimeError("Redis is unavailable.")

    otp = _generate_otp()
    payload = json.dumps(
        {
            "otp": otp,
            "attempts": 0,
        }
    )
    key = f"{_PENDING_PREFIX}{email}"
    await redis.setex(key, settings.OTP_EXPIRE_SECONDS, payload)
    logger.info("OTP stored for %s (TTL=%ss)", email, settings.OTP_EXPIRE_SECONDS)
    return otp


async def set_pending_user_id(email: str, user_id: int) -> None:
    redis = get_redis_client()
    if redis is None:
        return

    key = f"{_PENDING_PREFIX}{email}"
    payload = await redis.get(key)
    if payload:
        data = json.loads(payload)
        data["user_id"] = str(user_id)
        ttl = await redis.ttl(key)
        if ttl > 0:
            await redis.setex(key, ttl, json.dumps(data))


async def verify_and_consume(email: str, submitted_otp: str) -> dict | None:
    redis = get_redis_client()
    if redis is None:
        raise RuntimeError("Redis is unavailable.")

    key = f"{_PENDING_PREFIX}{email}"

    status, data = await redis.eval(
        _VERIFY_LUA_SCRIPT,
        1,  # numkeys
        key,
        submitted_otp,
        str(settings.OTP_MAX_ATTEMPTS),
    )

    if status == 0:
        # Correct OTP — entry was consumed by the script
        # data is the user_id string
        logger.info("OTP verified and consumed for %s", email)
        if data and data.strip():
            return {"user_id": data}
        return None

    if status == 1:
        logger.warning(
            "Max OTP attempts for %s — entry deleted",
            email,
        )
        return None

    if status == 2:
        logger.warning(
            "Wrong OTP for %s (attempt %s/%d)",
            email,
            data,
            settings.OTP_MAX_ATTEMPTS,
        )
        return None

    # status == 3: key does not exist
    logger.info("No pending OTP for %s (expired or never set)", email)
    return None


async def has_pending_registration(email: str) -> bool:
    """
    Check if a pending OTP registration exists for this email.

    Returns False when:
    - No pending registration exists
    - Redis is unavailable (logs a warning)
    """
    redis = get_redis_client()
    if redis is None:
        logger.warning(
            "has_pending_registration: Redis unavailable for %s — returning False",
            email,
        )
        return False
    return bool(await redis.exists(f"{_PENDING_PREFIX}{email}"))


async def delete_pending_registration(email: str) -> None:
    redis = get_redis_client()
    if redis is None:
        return
    await redis.delete(f"{_PENDING_PREFIX}{email}")
    logger.info("Pending OTP cancelled for %s", email)


# ── Password Reset OTP (separate Redis prefix) ─────────────────────────────────

_RESET_PREFIX = "otp:reset:"


async def store_reset_otp(email: str, user_id: int) -> str:
    redis = get_redis_client()
    if redis is None:
        raise RuntimeError("Redis is unavailable.")

    otp = _generate_otp()
    payload = json.dumps(
        {
            "otp": otp,
            "attempts": 0,
            "user_id": str(user_id),
        }
    )
    key = f"{_RESET_PREFIX}{email}"
    await redis.setex(key, settings.OTP_EXPIRE_SECONDS, payload)
    logger.info(
        "Reset OTP stored for %s (user_id=%s, TTL=%ss)",
        email,
        user_id,
        settings.OTP_EXPIRE_SECONDS,
    )
    return otp


async def verify_reset_otp(email: str, submitted_otp: str) -> dict | None:
    """
    Verify a password reset OTP using the same Lua script but with the reset prefix.
    Returns {user_id: str} on success, None on failure.
    """
    redis = get_redis_client()
    if redis is None:
        raise RuntimeError("Redis is unavailable.")

    key = f"{_RESET_PREFIX}{email}"

    status, data = await redis.eval(
        _VERIFY_LUA_SCRIPT,
        1,  # numkeys
        key,
        submitted_otp,
        str(settings.OTP_MAX_ATTEMPTS),
    )

    if status == 0:
        # Correct OTP — entry was consumed by the script
        logger.info("Reset OTP verified and consumed for %s", email)
        if data and data.strip():
            return {"user_id": data}
        return None

    if status == 1:
        logger.warning("Max reset OTP attempts for %s — entry deleted", email)
        return None

    if status == 2:
        logger.warning(
            "Wrong reset OTP for %s (attempt %s/%d)",
            email,
            data,
            settings.OTP_MAX_ATTEMPTS,
        )
        return None

    # status == 3: key does not exist
    logger.info("No pending reset OTP for %s (expired or never set)", email)
    return None


async def delete_reset_otp(email: str) -> None:
    """Delete a pending reset OTP record (e.g. on email send failure)."""
    redis = get_redis_client()
    if redis is None:
        return
    await redis.delete(f"{_RESET_PREFIX}{email}")
    logger.info("Reset OTP deleted for %s", email)
