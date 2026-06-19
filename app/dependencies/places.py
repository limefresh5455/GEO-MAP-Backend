from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_places import GooglePlacesClient
from app.repositories.redis_repository import RedisRepository
from app.services.places_service import PlacesService


def get_redis_repo() -> RedisRepository:
    return RedisRepository(get_redis_client())


def get_places_service(
    request: Request,
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
) -> PlacesService:
    # B10: Inject the shared httpx client from app.state
    http_client = getattr(request.app.state, "http_nearby", None)
    google_client = GooglePlacesClient(http_client=http_client)
    return PlacesService(
        db=db,
        redis_repo=redis_repo,
        google_client=google_client,
    )
