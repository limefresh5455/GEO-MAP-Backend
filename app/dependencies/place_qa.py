"""
FastAPI dependency providers for the Place Q&A layer.

Wires together:
  - SQLAlchemy DB session
  - OpenAIEmbeddingClient  (shared with Phase 3 — handles both embed + chat)
  - PineconeClient
  - PlaceQAService
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.integrations.pinecone_client import PineconeClient
from app.services.place_qa_service import PlaceQAService


def get_openai_client() -> OpenAIEmbeddingClient:
    return OpenAIEmbeddingClient()


def get_pinecone_client() -> PineconeClient:
    return PineconeClient()


def get_place_qa_service(
    db: Session = Depends(get_db),
    openai_client: OpenAIEmbeddingClient = Depends(get_openai_client),
    pinecone_client: PineconeClient = Depends(get_pinecone_client),
) -> PlaceQAService:
    return PlaceQAService(
        db=db,
        openai_client=openai_client,
        pinecone_client=pinecone_client,
    )
