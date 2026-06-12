import logging
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(__name__)
_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    if _redis_client is None:
        raise RuntimeError(
            "Redis client not initialised. Call initialise_redis() on startup."
        )
    return _redis_client


async def initialise_redis() -> None:
    global _redis_client
    try:
        _redis_client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await _redis_client.ping()
        logger.info(
            "Redis connection established at %s:%s",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
        )
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        raise


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")
