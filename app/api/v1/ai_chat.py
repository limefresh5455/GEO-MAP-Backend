import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.models.user import User
from app.schemas.ai_chat import AIChatResponse, AIChatStartRequest
from app.services.ai_chat_service import AIChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Travel Agent"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/message", response_model=AIChatResponse)
@limiter.limit("30/minute")
async def chat_message(
    request: Request,
    payload: AIChatStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AIChatResponse:
    """
    **Example — new session:**
    ```json
    { "query": "Plan a 2-day trip to Jaipur" }
    ```
    **Example — continue session:**
    ```json
    { "query": "What about hotels?", "session_id": "3f2a1b4c-8e9d-4a2b-b1c3-d4e5f6a7b8c9" }
    ```
    """
    # Session ID priority: header > body
    # Header value is a plain UUID string — no int() cast needed
    session_id: Optional[str] = payload.session_id
    session_id_header = request.headers.get("X-Chat-Session-Id")
    if session_id_header:
        session_id = session_id_header.strip() or None

    openai_client: OpenAIEmbeddingClient = getattr(request.app.state, "openai_client")
    service = AIChatService(db=db, openai_client=openai_client)

    try:
        return await service.chat(
            user_id=current_user.id,
            session_id=session_id,
            query=payload.query,
        )
    except Exception:
        logger.exception(
            "/chat/message failed (user_id=%s session_id=%s)",
            current_user.id, session_id,
        )
        raise
