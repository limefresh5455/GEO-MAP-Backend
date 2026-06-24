import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.rate_limiter import shared_limiter as limiter
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.exceptions.custom_exceptions import BadRequestError
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.models.user import User
from app.schemas.ai_chat import AIChatResponse, AIChatStartRequest
from app.services.ai_chat_service import AIChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Travel Agent"])


@router.post("/message", response_model=AIChatResponse)
@limiter.limit("30/minute")
async def chat_message(
    request: Request,
    payload: AIChatStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AIChatResponse:
    """
    **Example — new session (omit session_id or send null/empty):**
    ```json
    { "query": "Plan a 2-day trip to Jaipur" }
    ```
    ```json
    { "query": "Plan a 2-day trip to Jaipur", "session_id": null }
    ```
    **Example — continue existing session:**
    ```json
    { "query": "What about hotels?", "session_id": "3f2a1b4c-8e9d-4a2b-b1c3-d4e5f6a7b8c9" }
    ```
    """
    # Step 1: Resolve session_id — header takes priority over body
    session_id: Optional[str] = payload.session_id
    session_id_header = request.headers.get("X-Chat-Session-Id")
    if session_id_header:
        header_sid = session_id_header.strip() or None
        if header_sid and session_id is not None and header_sid != session_id:
            logger.warning(
                "X-Chat-Session-Id header (%s) overrides body session_id (%s) "
                "for user_id=%s",
                header_sid,
                session_id,
                current_user.id,
            )
        session_id = header_sid

    # Step 2: Normalize session_id — strip whitespace, treat empty as None
    if session_id is not None:
        session_id = session_id.strip()
        if session_id == "":
            session_id = None

    # Step 3: If session_id is provided, validate that it is a proper UUID
    if session_id is not None:
        try:
            uuid.UUID(session_id)
        except (ValueError, AttributeError):
            raise BadRequestError(
                f"Invalid session_id format: '{session_id}'. "
                "Expected a valid UUID v4 string (e.g. "
                "'3f2a1b4c-8e9d-4a2b-b1c3-d4e5f6a7b8c9')."
            )

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
            current_user.id,
            session_id,
        )
        raise
