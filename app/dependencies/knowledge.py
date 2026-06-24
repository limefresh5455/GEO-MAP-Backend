from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.integrations.pinecone_client import PineconeClient
from app.services.knowledge_service import KnowledgeService


def get_knowledge_service(
    request: Request,
    db: Session = Depends(get_db),
) -> KnowledgeService:
    pinecone_client: PineconeClient = getattr(
        request.app.state, "pinecone_client", None
    )
    if pinecone_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pinecone client not initialized. Check server logs for startup errors.",
        )

    openai_client: OpenAIEmbeddingClient = getattr(
        request.app.state, "openai_client", None
    )
    if openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI client not initialized. Check server logs for startup errors.",
        )

    return KnowledgeService(
        db=db,
        openai_client=openai_client,
        pinecone_client=pinecone_client,
    )
