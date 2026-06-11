from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_places import GooglePlacesClient
from app.repositories.redis_repository import RedisRepository
from app.services.places_service import PlacesService


def get_redis_repo() -> RedisRepository:
    client = get_redis_client()
    return RedisRepository(client)


def get_google_client() -> GooglePlacesClient:
    return GooglePlacesClient()


def get_places_service(
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
    google_client: GooglePlacesClient = Depends(get_google_client),
) -> PlacesService:
    return PlacesService(
        db=db,
        redis_repo=redis_repo,
        google_client=google_client,
    )
