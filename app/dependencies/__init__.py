# Shared dependency functions
from app.core.redis import get_redis_client
from app.repositories.redis_repository import RedisRepository


def get_redis_repo() -> RedisRepository:
    """
    Shared RedisRepository dependency.
    Used by discovery, place_details, and routes dependencies.
    Import this function instead of redefining it in each module.
    """
    return RedisRepository(get_redis_client())
