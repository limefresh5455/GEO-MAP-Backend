from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_autocomplete import GoogleAutocompleteClient
from app.integrations.google_places import GooglePlacesClient
from app.integrations.google_text_search import GoogleTextSearchClient
from app.repositories.redis_repository import RedisRepository
from app.services.discovery_service import DiscoveryService


def get_redis_repo() -> RedisRepository:
    return RedisRepository(get_redis_client())


def get_discovery_service(
    request: Request,
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
) -> DiscoveryService:
    # B10: Inject shared httpx clients from app.state
    http_text = getattr(request.app.state, "http_text_search", None)
    http_nearby = getattr(request.app.state, "http_nearby", None)
    http_autocomplete = getattr(request.app.state, "http_autocomplete", None)
    text_client = GoogleTextSearchClient(http_client=http_text)
    nearby_client = GooglePlacesClient(http_client=http_nearby)
    autocomplete_client = GoogleAutocompleteClient(http_client=http_autocomplete)
    return DiscoveryService(
        db=db,
        redis_repo=redis_repo,
        text_client=text_client,
        nearby_client=nearby_client,
        autocomplete_client=autocomplete_client,
    )
