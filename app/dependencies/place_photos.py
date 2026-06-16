"""
Dependency providers for the Place Photos layer.

Follows the same injection pattern as all other Google-client dependencies:
  - Reads the shared httpx.AsyncClient from app.state (B10 pattern)
  - Falls back to None gracefully (per-call client used in tests)
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_place_photos import GooglePlacePhotosClient
from app.repositories.redis_repository import RedisRepository
from app.services.place_photos_service import PlacePhotosService


def get_redis_repo() -> RedisRepository:
    return RedisRepository(get_redis_client())


def get_place_photos_service(
    request: Request,
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
) -> PlacePhotosService:
    """
    Build a PlacePhotosService with:
    - the shared httpx.AsyncClient from app.state (registered in main.py)
    - the injected DB session
    - the Redis repository

    The http_photos client is registered on app.state during startup.
    """
    http_client = getattr(request.app.state, "http_photos", None)
    photos_client = GooglePlacePhotosClient(http_client=http_client)

    return PlacePhotosService(
        db=db,
        redis_repo=redis_repo,
        photos_client=photos_client,
    )
