"""
Dependency providers for the Place Details layer.

B10 FIX: GooglePlaceDetailsClient receives the shared httpx.AsyncClient
from app.state for connection pooling.

Phase 3: Injects KnowledgeService to enable automatic background knowledge
sync after fetching place details from Google.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_place_details import GooglePlaceDetailsClient
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.integrations.pinecone_client import PineconeClient
from app.repositories.redis_repository import RedisRepository
from app.services.knowledge_service import KnowledgeService
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
    
    # Phase 3: Inject KnowledgeService for auto background sync
    # Read OpenAI and Pinecone clients from app.state (initialized in main.py)
    openai_client = getattr(request.app.state, "openai_client", None)
    pinecone_client = getattr(request.app.state, "pinecone_client", None)
    
    knowledge_service = None
    if openai_client and pinecone_client:
        knowledge_service = KnowledgeService(
            db=db,
            openai_client=openai_client,
            pinecone_client=pinecone_client,
        )
    
    return PlaceDetailsService(
        db=db,
        redis_repo=redis_repo,
        google_client=google_client,
        knowledge_service=knowledge_service,
    )
