import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import tiktoken
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.repositories.ai_chat_repository import AIChatRepository
from app.schemas.ai_chat import AIChatResponse

logger = logging.getLogger(__name__)

_ENCODER = tiktoken.encoding_for_model("gpt-4o-mini")

_SYSTEM_PROMPT = """You are a helpful AI travel assistant. Follow these rules:
- Answer conversationally in English.
- Maintain continuity using the conversation history provided.
- Help users plan trips, discover places, and answer travel-related questions.
- If the user asks something ambiguous, ask a clarifying question.
"""


def _estimate_tokens(text: str) -> int:
    return max(1, len(_ENCODER.encode(text)))


class AIChatService:
    def __init__(
        self,
        *,
        db: Session,
        openai_client: OpenAIEmbeddingClient,
    ) -> None:
        self.db = db
        self.openai_client = openai_client
        self.repo = AIChatRepository(db)

    def _generate_title(self, query: str) -> str:
        title = query.split("\n")[0][:60]
        return title if title else "New Chat"

    def _build_messages_for_openai(
        self, history_messages: List, *, user_query: str
    ) -> List[dict]:
        messages: List[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for m in history_messages:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_query})
        return messages

    async def chat(
        self,
        *,
        user_id: int,
        session_id: Optional[str],
        query: str,
    ) -> AIChatResponse:
        start = time.monotonic()
        model_used = settings.OPENAI_CHAT_MODEL

        session = None
        is_new_session = False

        # Look up existing session if client provided one
        if session_id is not None:
            session = self.repo.get_session(session_id=session_id, user_id=user_id)

        # If client gave a session_id but we can't find it → error
        # (don't silently create a new session — that loses continuity)
        if session_id is not None and session is None:
            from app.exceptions.custom_exceptions import NotFoundError
            raise NotFoundError(f"Chat session '{session_id}' not found")

        # No session_id provided → create a fresh session
        if session is None:
            if self.repo.count_user_sessions(user_id=user_id) >= settings.MAX_SESSIONS_PER_USER:
                from app.exceptions.custom_exceptions import BadRequestError
                raise BadRequestError(
                    f"Maximum session limit ({settings.MAX_SESSIONS_PER_USER}) reached. "
                    "Please delete old sessions before creating new ones."
                )

            session = self.repo.create_session(
                user_id=user_id,
                title=self._generate_title(query),
            )
            self.db.flush()
            is_new_session = True

        # Load recent history for context (last 5 exchanges = 10 messages)
        try:
            history = self.repo.get_recent_messages(session_id=session.id, limit=10)
        except Exception:
            logger.exception(
                "Failed to fetch chat history (user_id=%s session_id=%s). "
                "Continuing without history.",
                user_id, session.id,
            )
            history = []

        # Build message list for OpenAI
        messages = self._build_messages_for_openai(history, user_query=query)

        # Enforce token budget — trim oldest history if needed
        max_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        while (
            sum(_estimate_tokens(m["content"]) for m in messages) > max_tokens
            and len(history) > 0
        ):
            history = history[1:]
            messages = self._build_messages_for_openai(history, user_query=query)

        answer = await self.openai_client.get_chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=800,
        )

        # Persist both messages + update timestamp in one commit
        try:
            self.repo.add_message(
                session_id=session.id,
                role="user",
                content=query,
                token_count=_estimate_tokens(query),
                model_used=model_used,
            )
            self.repo.add_message(
                session_id=session.id,
                role="assistant",
                content=answer,
                token_count=_estimate_tokens(answer),
                model_used=model_used,
            )
            self.repo.update_session_timestamp(session=session)
            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to persist chat messages (user_id=%s session_id=%s).",
                user_id, session.id,
            )
            self.db.rollback()
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "AIChat complete — user=%s session=%s new=%s latency=%dms",
            user_id, session.id, is_new_session, latency_ms,
        )

        return AIChatResponse(
            success=True,
            session_id=session.id,        # UUID string
            answer=answer,
            is_new_session=is_new_session,
            title=session.title if is_new_session else None,
            timestamp=datetime.now(timezone.utc),
        )
