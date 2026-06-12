"""
FastAPI dependency providers for the Discovery layer.

Wires together:
  - SQLAlchemy DB session
  - Redis repository
  - GoogleTextSearchClient
  - GooglePlacesClient  (existing nearby client, reused here)
  - DiscoveryService
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_places import GooglePlacesClient
from app.integrations.google_text_search import GoogleTextSearchClient
from app.repositories.redis_repository import RedisRepository
from app.services.discovery_service import DiscoveryService


def get_redis_repo() -> RedisRepository:
    client = get_redis_client()
    return RedisRepository(client)


def get_text_search_client() -> GoogleTextSearchClient:
    return GoogleTextSearchClient()


def get_nearby_client() -> GooglePlacesClient:
    return GooglePlacesClient()


def get_discovery_service(
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
    text_client: GoogleTextSearchClient = Depends(get_text_search_client),
    nearby_client: GooglePlacesClient = Depends(get_nearby_client),
) -> DiscoveryService:
    return DiscoveryService(
        db=db,
        redis_repo=redis_repo,
        text_client=text_client,
        nearby_client=nearby_client,
    )
