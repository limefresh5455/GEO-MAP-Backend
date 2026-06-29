import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional
import tiktoken
from sqlalchemy.orm import Session
from app.core.config import settings
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.repositories.ai_chat_repository import AIChatRepository
from app.schemas.ai_chat import AIChatResponse
from app.services.credit_service import CreditService

logger = logging.getLogger(__name__)

# Lazy tiktoken encoder — avoids crashing the module at import time if
# tiktoken has network issues or the model name changes.
_ENCODER = None


def _get_encoder():
    global _ENCODER
    if _ENCODER is None:
        try:
            _ENCODER = tiktoken.encoding_for_model("gpt-4o-mini")
        except Exception as exc:
            logger.warning(
                "Failed to initialize tiktoken encoder for gpt-4o-mini: %s. "
                "Falling back to approximate token counting.",
                exc,
            )
            _ENCODER = None
    return _ENCODER


_SYSTEM_PROMPT = """You are a professional travel assistant.

Goal
Help users plan trips, discover places, compare options, and answer travel-related questions accurately and efficiently.

Language and tone
- Answer in clear, natural English.
- Be direct, structured, and useful.
- Keep continuity with the conversation history.
- Do not add filler, hype, or unnecessary commentary.

Accuracy rules
- Do not guess facts that could be wrong.
- Do not invent prices, schedules, opening hours, visa rules, availability, weather, transport times, or local regulations.
- If information is uncertain, say so clearly.
- Separate verified information from assumptions.
- When current or location-specific information matters, ask for details or verify before answering.
- If a request is ambiguous, ask one concise clarifying question before proceeding.

Travel planning behavior
- Understand the user’s goal, budget, dates, origin, destination, group size, pace, and preferences when relevant.
- Recommend options that fit the user’s constraints.
- Consider practicality, travel time, season, safety, and cost.
- Give balanced suggestions, not just popular ones.

Response format
Use this structure when helpful:
1. Direct answer
2. Key details
3. Options or recommendations
4. Trade-offs or caveats
5. Next step

Quality rules
- Be specific.
- Be realistic.
- Do not overstate confidence.
- Do not fabricate sources.
- Avoid repetition.
- Keep recommendations actionable.

If the user asks for an itinerary
- Organize it by day or time block.
- Include estimated pace and transit considerations.
- Flag anything that needs confirmation.

If the user asks for comparisons
- Compare by cost, convenience, travel time, fit, and risk.
- End with a clear recommendation.

If the user asks for a destination suggestion
- Match suggestions to the user’s budget, season, interests, and trip length.
- Give 3 to 5 strong options max.

If the user asks for live or recent information
- State that it should be verified with current sources before booking or committing.
- Do not present stale information as current.

Never
- Never hallucinate.
- Never pretend to have checked live data when you have not.
- Never invent personal experience.
- Never output vague travel advice when a precise answer is possible.
"""


def _estimate_tokens(text: str) -> int:
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return max(1, len(encoder.encode(text)))
        except Exception:
            pass
    # Fallback: approximate by chars / 4 (roughly 4 chars per token)
    return max(1, len(text) // 4 + 1)


class AIChatService:
    CHAT_COST = 5  # credits deducted per message

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

        # ── Step 0: Credit check before any expensive work ──
        await CreditService.check_balance(self.db, user_id, self.CHAT_COST)

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
            current_count = self.repo.count_user_sessions(user_id=user_id)
            if current_count >= settings.MAX_SESSIONS_PER_USER:
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
        # If the DB query fails, continue without history rather than crashing
        try:
            history = self.repo.get_recent_messages(session_id=session.id, limit=10)
        except Exception:
            logger.exception(
                "Failed to fetch chat history (user_id=%s session_id=%s). "
                "Continuing without history. Response may lack conversation context.",
                user_id,
                session.id,
            )
            history = []

        # Build message list for OpenAI
        messages = self._build_messages_for_openai(history, user_query=query)

        # Enforce token budget — trim oldest history until under budget (O(n) with running total)
        max_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        system_tokens = _estimate_tokens(_SYSTEM_PROMPT)
        query_tokens = _estimate_tokens(query)
        history_tokens = [_estimate_tokens(m.content) for m in history]
        total_tokens = system_tokens + sum(history_tokens) + query_tokens
        while total_tokens > max_tokens and history_tokens:
            removed = history_tokens.pop(0)  # remove oldest history entry's tokens
            total_tokens -= removed
            history = history[1:]
        messages = self._build_messages_for_openai(history, user_query=query)

        answer = await self.openai_client.get_chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=800,
        )

        # Persist both messages + deduct credits + update timestamp in one commit
        try:
            await CreditService.deduct(self.db, user_id, self.CHAT_COST)
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
                user_id,
                session.id,
            )
            self.db.rollback()
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "AIChat complete — user=%s session=%s new=%s latency=%dms",
            user_id,
            session.id,
            is_new_session,
            latency_ms,
        )

        return AIChatResponse(
            success=True,
            session_id=session.id,  # UUID string
            answer=answer,
            is_new_session=is_new_session,
            title=session.title if is_new_session else None,
            timestamp=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Streaming chat — token-by-token via async generator
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        *,
        user_id: int,
        session_id: Optional[str],
        query: str,
    ) -> AsyncGenerator[str, None]:
        """
        Like chat() but yields answer tokens as they arrive from OpenAI.
        Session/credit setup and final persistence happen around the stream.

        Yields JSON-encoded control events and content tokens:
        - {"type": "metadata", "session_id": ..., "is_new_session": ...}
        - {"type": "token", "content": "..."}
        - {"type": "done", "title": ...}
        """
        model_used = settings.OPENAI_CHAT_MODEL

        # Credit check
        await CreditService.check_balance(self.db, user_id, self.CHAT_COST)

        session = None
        is_new_session = False

        # Resolve session
        if session_id is not None:
            session = self.repo.get_session(session_id=session_id, user_id=user_id)

        if session_id is not None and session is None:
            from app.exceptions.custom_exceptions import NotFoundError

            raise NotFoundError(f"Chat session '{session_id}' not found")

        if session is None:
            current_count = self.repo.count_user_sessions(user_id=user_id)
            if current_count >= settings.MAX_SESSIONS_PER_USER:
                from app.exceptions.custom_exceptions import BadRequestError

                raise BadRequestError(
                    f"Maximum session limit ({settings.MAX_SESSIONS_PER_USER}) reached. "
                    "Please delete old sessions before creating new ones."
                )
            session = self.repo.create_session(
                user_id=user_id,
                title="New Chat",  # Will be updated in background after streaming
            )
            self.db.flush()
            is_new_session = True

        # Yield metadata so client knows session_id immediately
        yield json.dumps(
            {
                "type": "metadata",
                "session_id": session.id,
                "is_new_session": is_new_session,
            }
        )

        # Load history for context
        try:
            history = self.repo.get_recent_messages(session_id=session.id, limit=10)
        except Exception:
            logger.exception(
                "Failed to fetch chat history (user_id=%s session_id=%s). "
                "Continuing without history.",
                user_id,
                session.id,
            )
            history = []

        messages = self._build_messages_for_openai(history, user_query=query)

        # Enforce token budget — trim oldest history until under budget
        max_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        history_tokens = [_estimate_tokens(m.content) for m in history]
        system_tokens = _estimate_tokens(_SYSTEM_PROMPT)
        query_tokens = _estimate_tokens(query)
        while (
            system_tokens + sum(history_tokens) + query_tokens > max_tokens
            and len(history_tokens) > 0
        ):
            history_tokens.pop(0)
            history = history[1:]
        messages = self._build_messages_for_openai(history, user_query=query)

        # Stream from OpenAI
        full_answer_parts: List[str] = []
        try:
            async for content in self.openai_client.stream_chat_with_history(
                messages=messages,
                temperature=0.7,
                max_tokens=800,
            ):
                full_answer_parts.append(content)
                yield json.dumps({"type": "token", "content": content})
        except Exception:
            logger.exception("OpenAI streaming failed during chat")
            raise

        answer = "".join(full_answer_parts)

        # Persist messages + deduct credits
        try:
            await CreditService.deduct(self.db, user_id, self.CHAT_COST)
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

            # Generate title for new sessions BEFORE commit
            if is_new_session:
                title = self._generate_title(query)
                session.title = title

            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to persist chat messages (user_id=%s session_id=%s).",
                user_id,
                session.id,
            )
            self.db.rollback()
            raise

        yield json.dumps(
            {
                "type": "done",
                "title": session.title if is_new_session else None,
            }
        )
