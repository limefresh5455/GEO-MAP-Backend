import logging
from datetime import datetime, timezone
from typing import Optional

from jose import jwt

from app.core.config import settings
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)


class TokenBlacklistService:
    # Redis key prefix for blacklisted tokens
    BLACKLIST_PREFIX = "token:blacklist:"

    @staticmethod
    def _get_token_key(token: str) -> str:
        """Generate Redis key for a token."""
        return f"{TokenBlacklistService.BLACKLIST_PREFIX}{token}"

    @staticmethod
    def _get_token_expiration(token: str) -> Optional[int]:
        try:
            # Decode without verification to get expiration
            payload = jwt.get_unverified_claims(token)
            exp = payload.get("exp")
            if exp is None:
                return None

            # Calculate seconds until expiration
            now = datetime.now(timezone.utc).timestamp()
            ttl = int(exp - now)

            # If already expired, return 0
            return max(0, ttl)
        except Exception as e:
            logger.warning(f"Failed to extract token expiration: {e}")
            return None

    @staticmethod
    async def blacklist_token(token: str) -> bool:
        redis_client = get_redis_client()
        if redis_client is None:
            logger.warning(
                "Cannot blacklist token — Redis unavailable. "
                "Token will remain valid until expiration."
            )
            return False

        try:
            # Get token expiration time
            ttl = TokenBlacklistService._get_token_expiration(token)
            if ttl is None or ttl <= 0:
                logger.info("Token already expired, not blacklisting")
                return True

            # Store token in Redis with expiration
            key = TokenBlacklistService._get_token_key(token)
            await redis_client.setex(key, ttl, "1")

            logger.info(
                f"Token blacklisted successfully (TTL: {ttl}s)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to blacklist token: {e}")
            return False

    @staticmethod
    async def is_token_blacklisted(token: str) -> bool:
        redis_client = get_redis_client()
        if redis_client is None:
            # If Redis is unavailable, we can't check blacklist
            # Log warning but allow the token (degraded mode)
            logger.debug("Redis unavailable — cannot check token blacklist")
            return False

        try:
            key = TokenBlacklistService._get_token_key(token)
            exists = await redis_client.exists(key)
            return bool(exists)

        except Exception as e:
            logger.error(f"Failed to check token blacklist: {e}")
            # On error, fail open (don't block valid users)
            return False

    @staticmethod
    async def get_blacklist_stats() -> dict:
        redis_client = get_redis_client()
        if redis_client is None:
            return {"available": False}

        try:
            # Count blacklisted tokens
            pattern = f"{TokenBlacklistService.BLACKLIST_PREFIX}*"
            keys = []
            async for key in redis_client.scan_iter(match=pattern, count=100):
                keys.append(key)

            return {
                "available": True,
                "blacklisted_count": len(keys),
            }

        except Exception as e:
            logger.error(f"Failed to get blacklist stats: {e}")
            return {"available": False, "error": str(e)}
