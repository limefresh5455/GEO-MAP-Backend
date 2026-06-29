import json
import logging
from typing import Any, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisRepository:

    def __init__(self, client: Optional[Redis]):
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
        lat = round(latitude, 4)
        lon = round(longitude, 4)
        return f"nearby:{user_id}:{lat}:{lon}:{radius}:{max_result_count}"

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a cached value. Returns None on miss, Redis error, or unavailable."""
        if self.client is None:
            return None
        try:
            raw = await self.client.get(key)
            if raw is None:
                logger.debug("Cache MISS: %s", key)
                return None
            logger.info("Cache HIT: %s", key)
            return json.loads(raw)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.error("Redis GET error for key '%s': %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Serialise and store a value with TTL. Accepts any JSON-serialisable value. Returns True on success."""
        if self.client is None:
            return False
        try:
            expiry = ttl or self.ttl
            await self.client.setex(key, expiry, json.dumps(value))
            logger.info("Cache SET: %s (TTL: %ss)", key, expiry)
            return True
        except (RedisError, TypeError, ValueError) as exc:
            logger.error("Redis SET error for key '%s': %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        if self.client is None:
            return False
        try:
            result = await self.client.delete(key)
            return result > 0
        except RedisError as exc:
            logger.error("Redis DELETE error for key '%s': %s", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        """Check existence without fetching the value."""
        if self.client is None:
            return False
        try:
            return bool(await self.client.exists(key))
        except RedisError as exc:
            logger.error("Redis EXISTS error for key '%s': %s", key, exc)
            return False

    async def get_ttl(self, key: str) -> int:
        """Return remaining TTL in seconds. -2 means key does not exist."""
        if self.client is None:
            return -2
        try:
            return await self.client.ttl(key)
        except RedisError as exc:
            logger.error("Redis TTL error for key '%s': %s", key, exc)
            return -2
