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
    http_client = getattr(request.app.state, "http_photos", None)
    photos_client = GooglePlacePhotosClient(http_client=http_client)

    return PlacePhotosService(
        db=db,
        redis_repo=redis_repo,
        photos_client=photos_client,
    )
