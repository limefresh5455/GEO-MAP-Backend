"""
Dependency providers for the Place Details layer.

B10 FIX: GooglePlaceDetailsClient receives the shared httpx.AsyncClient
from app.state for connection pooling.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_place_details import GooglePlaceDetailsClient
from app.repositories.redis_repository import RedisRepository
from app.services.place_details_service import PlaceDetailsService


def get_redis_repo() -> RedisRepository:
    return RedisRepository(get_redis_client())


def get_place_details_service(
    request: Request,
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
) -> PlaceDetailsService:
    # B10: Inject shared httpx client from app.state
    http_client = getattr(request.app.state, "http_place_details", None)
    google_client = GooglePlaceDetailsClient(http_client=http_client)
    return PlaceDetailsService(
        db=db,
        redis_repo=redis_repo,
        google_client=google_client,
    )
