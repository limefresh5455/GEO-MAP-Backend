import json
import logging
from typing import Optional

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisRepository:
    """
    Low-level Redis operations.
    No business logic — only get, set, delete, exists, key generation.
    """

    def __init__(self, client: Redis):
        self.client = client
        self.ttl = settings.REDIS_CACHE_TTL

    def generate_nearby_cache_key(
        self,
        user_id: int,
        latitude: float,
        longitude: float,
        radius: float,
        max_result_count: int,
    ) -> str:
        """
        Deterministic cache key scoped to a specific user + search parameters.

        Format: nearby:{user_id}:{lat}:{lon}:{radius}:{count}

        Coordinates rounded to 6 decimal places (~11cm precision) to prevent
        GPS noise from generating spurious cache misses.

        Examples:
          nearby:15:21.251384:81.629639:500:20   ← user 15, Raipur
          nearby:15:19.076:72.8777:500:20        ← user 15, Mumbai (after location change)
          nearby:42:19.076:72.8777:500:20        ← user 42, same coords but different user
        """
        lat = round(latitude, 6)
        lon = round(longitude, 6)
        return f"nearby:{user_id}:{lat}:{lon}:{radius}:{max_result_count}"

    async def get(self, key: str) -> Optional[dict]:
        """Retrieve a cached value. Returns None on miss or Redis error."""
        try:
            raw = await self.client.get(key)
            if raw is None:
                logger.debug("Cache MISS: %s", key)
                return None
            logger.info("Cache HIT: %s", key)
            return json.loads(raw)
        except Exception as exc:
            logger.error("Redis GET error for key '%s': %s", key, exc)
            return None

    async def set(self, key: str, value: dict, ttl: Optional[int] = None) -> bool:
        """Serialise and store a value with TTL. Returns True on success."""
        try:
            expiry = ttl or self.ttl
            await self.client.setex(key, expiry, json.dumps(value))
            logger.info("Cache SET: %s (TTL: %ss)", key, expiry)
            return True
        except Exception as exc:
            logger.error("Redis SET error for key '%s': %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        try:
            result = await self.client.delete(key)
            return result > 0
        except Exception as exc:
            logger.error("Redis DELETE error for key '%s': %s", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        """Check existence without fetching the value."""
        try:
            return bool(await self.client.exists(key))
        except Exception as exc:
            logger.error("Redis EXISTS error for key '%s': %s", key, exc)
            return False

    async def get_ttl(self, key: str) -> int:
        """Return remaining TTL in seconds. -2 means key does not exist."""
        try:
            return await self.client.ttl(key)
        except Exception as exc:
            logger.error("Redis TTL error for key '%s': %s", key, exc)
            return -2
