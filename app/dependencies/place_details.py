"""
FastAPI dependency providers for the Place Details layer.

Wires together:
  - SQLAlchemy DB session
  - Redis repository
  - GooglePlaceDetailsClient
  - PlaceDetailsService
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_place_details import GooglePlaceDetailsClient
from app.repositories.redis_repository import RedisRepository
from app.services.place_details_service import PlaceDetailsService


def get_redis_repo() -> RedisRepository:
    client = get_redis_client()
    return RedisRepository(client)


def get_google_details_client() -> GooglePlaceDetailsClient:
    return GooglePlaceDetailsClient()


def get_place_details_service(
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
    google_client: GooglePlaceDetailsClient = Depends(get_google_details_client),
) -> PlaceDetailsService:
    return PlaceDetailsService(
        db=db,
        redis_repo=redis_repo,
        google_client=google_client,
    )
