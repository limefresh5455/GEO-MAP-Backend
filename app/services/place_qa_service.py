import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import tiktoken
from sqlalchemy.orm import Session
from app.core.config import settings
from app.exceptions.custom_exceptions import BadRequestError, NotFoundError
from app.exceptions.places import PlaceDetailNotFoundError
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.integrations.pinecone_client import PineconeClient
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.place_qa_repository import PlaceQARepository
from app.schemas.place_qa import (
    AnswerSource,
    GroundingFragment,
    PlaceQuestionRequest,
    PlaceQuestionResponse,
    TechnicalMetadata,
    PlaceInfo,
    PlaceQASessionListItem,
)
from app.services.credit_service import CreditService

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.30

_SYSTEM_PROMPT_TEMPLATE = """You are a helpful local place-discovery assistant. Answer questions about places using the PLACE CONTEXT provided below.

Rules:
- Respond in English.
- Start with a direct answer, then add relevant context.
- If asked about a specific feature (hours, price, parking), give the exact value if available.
- If the information is explicitly in the PLACE CONTEXT, state it directly.
- If information is not in the PLACE CONTEXT, say you don't have that specific information. Do not make up details.
- Use short paragraphs and bullet points only when listing multiple items.
- Keep answers concise.

PLACE CONTEXT
{context_block}

Answer the user's question using the information above.
"""

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
            _ENCODER = None  # sentinel — will retry on next call
    return _ENCODER


def _build_structured_facts_block(place) -> str:
    sections = []

    basic_info = []
    if place.display_name:
        basic_info.append(f"This is {place.display_name}")
    if place.formatted_address:
        basic_info.append(f"located at {place.formatted_address}")
    if place.primary_type:
        type_label = place.primary_type.replace("_", " ").title()
        basic_info.append(f"It's a {type_label}")
    if basic_info:
        sections.append(". ".join(basic_info) + ".")

    rating_info = []
    if place.rating is not None:
        rating_info.append(f"Rating: {place.rating} out of 5 stars")
    if place.user_rating_count is not None:
        rating_info.append(f"based on {place.user_rating_count} reviews")
    if rating_info:
        sections.append(" ".join(rating_info) + ".")

    if place.business_status:
        status = place.business_status.replace("_", " ").lower()
        if status == "operational":
            sections.append("The business is currently operational.")
        else:
            sections.append(f"Business status: {status}.")

    if place.open_now is not None:
        sections.append(
            "Currently OPEN for customers." if place.open_now else "Currently CLOSED."
        )

    if place.opening_hours and isinstance(place.opening_hours, dict):
        weekdays = place.opening_hours.get("weekday_descriptions") or []
        if weekdays:
            sections.append("Operating hours:")
            for day in weekdays:
                sections.append(f"  • {day}")

    contact_items = []
    if place.international_phone_number:
        contact_items.append(f"Phone: {place.international_phone_number}")
    if place.website_uri:
        contact_items.append(f"Website: {place.website_uri}")
    if place.google_maps_uri:
        contact_items.append(f"Google Maps: {place.google_maps_uri}")
    if contact_items:
        sections.append("Contact information:")
        for item in contact_items:
            sections.append(f"  • {item}")

    if place.price_level:
        price = place.price_level.replace("PRICE_LEVEL_", "").lower()
        price_descriptions = {
            "free": "Free admission or no cost",
            "inexpensive": "Budget-friendly (₹)",
            "moderate": "Moderately priced (₹₹)",
            "expensive": "Upscale pricing (₹₹₹)",
            "very_expensive": "Premium/luxury pricing (₹₹₹₹)",
        }
        sections.append(
            f"Price range: {price_descriptions.get(price, price.capitalize())}"
        )

    if place.wheelchair_accessible_entrance is not None:
        if place.wheelchair_accessible_entrance:
            sections.append("♿ Wheelchair accessible entrance available.")
        else:
            sections.append("Note: No wheelchair accessible entrance.")

    if place.editorial_summary:
        sections.append(f"\nAbout this place: {place.editorial_summary}")

    # Extended data: amenities, services, food, atmosphere
    if place.extended_data and isinstance(place.extended_data, dict):
        ext = place.extended_data

        # Dining/service flags
        dining_labels = []
        for flag, label in [
            ("dineIn", "Dine-in"),
            ("takeout", "Takeout"),
            ("delivery", "Delivery"),
            ("curbsidePickup", "Curbside pickup"),
            ("reservable", "Reservations accepted"),
        ]:
            if ext.get(flag) is True:
                dining_labels.append(label)
        if dining_labels:
            sections.append("Services: " + ", ".join(dining_labels) + ".")

        # Food & drink
        food_labels = []
        for flag, label in [
            ("servesBreakfast", "Breakfast"),
            ("servesLunch", "Lunch"),
            ("servesDinner", "Dinner"),
            ("servesBeer", "Beer"),
            ("servesWine", "Wine"),
            ("servesCocktails", "Cocktails"),
        ]:
            if ext.get(flag) is True:
                food_labels.append(label)
        if food_labels:
            sections.append("Food & drink: Serves " + ", ".join(food_labels) + ".")

        # Atmosphere & features
        atmos_labels = []
        for flag, label in [
            ("outdoorSeating", "Outdoor seating"),
            ("liveMusic", "Live music"),
            ("goodForChildren", "Good for children"),
            ("goodForGroups", "Good for groups"),
            ("allowsDogs", "Allows dogs"),
            ("restroom", "Restroom available"),
        ]:
            if ext.get(flag) is True:
                atmos_labels.append(label)
        if atmos_labels:
            sections.append("Atmosphere: " + ", ".join(atmos_labels) + ".")

        # Parking
        parking_types = []
        for k, v in ext.items():
            if k.startswith("parking_") and v is True:
                label = k.replace("parking_", "").replace("_", " ").title()
                parking_types.append(label)
        if parking_types:
            sections.append("Parking available: " + ", ".join(parking_types) + ".")

        # Payment
        payment_types = []
        for k, v in ext.items():
            if k.startswith("payment_") and v is True:
                label = k.replace("payment_", "").replace("_", " ").title()
                payment_types.append(label)
        if payment_types:
            sections.append("Payment methods: " + ", ".join(payment_types) + ".")

        # EV charging
        if ext.get("ev_charger_options"):
            ev = ext["ev_charger_options"]
            if isinstance(ev, dict):
                count = ev.get("chargerCount", "some")
                sections.append(f"🔌 EV charging available ({count} chargers).")

        # Wikipedia extract (if available)
        wiki_extract = ext.get("wikipedia_extract")
        if wiki_extract:
            sections.append(f"\n📖 From Wikipedia: {wiki_extract[:500]}")

        # Neighborhood / location context
        for key in ("neighborhood", "sublocality", "locality", "state", "country"):
            val = ext.get(key)
            if val:
                display_key = key.replace("_", " ").title()
                sections.append(f"📍 {display_key}: {val}")

    return "\n".join(sections)


def _compute_confidence(scores: List[float]) -> Optional[float]:
    if not scores:
        return None
    return round(sum(scores) / len(scores), 3)


def _estimate_tokens(text: str) -> int:
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return max(1, len(encoder.encode(text)))
        except Exception:
            pass
    # Fallback: approximate by chars / 4 (roughly 4 chars per token)
    return max(1, len(text) // 4 + 1)


class PlaceQAService:
    CHAT_COST = 5
    _PLACE_CACHE_TTL = 300  # 5 minutes
    _PLACE_CACHE_MAX_SIZE = 200  # prevent memory leak
    # Class-level cache shared across all request instances.
    # Async Python is single-threaded, so dict access is safe.
    # Key: place_id -> (place_detail_obj, cached_at_timestamp)
    _place_cache: Dict[str, tuple] = {}

    def __init__(
        self,
        db: Session,
        openai_client: OpenAIEmbeddingClient,
        pinecone_client: PineconeClient,
    ) -> None:
        self.db = db
        self.openai_client = openai_client
        self.pinecone_client = pinecone_client
        self.knowledge_repo = KnowledgeRepository(db)
        self.qa_repo = PlaceQARepository(db)

    # ── Caching Helper ────────────────────────────────────────────────────

    def _get_cached_place(self, place_id: str):
        """
        Return place detail from a short-lived in-memory cache, falling back
        to the database on a cache miss or expiry.

        Uses a class-level cache so place details persist across requests
        within the same server process (up to the TTL).

        NOTE: We re-attach the ORM object to the current session via
        self.db.add() to avoid DetachedInstanceError when accessing
        attributes that have been expired by a previous commit or
        when the original session has been closed.
        """
        now = time.time()
        cached = PlaceQAService._place_cache.get(place_id)
        if cached is not None:
            place, cached_at = cached
            if now - cached_at < self._PLACE_CACHE_TTL:
                # Re-attach detached ORM object to the current session
                # so lazy-loaded attributes work correctly.
                self.db.add(place)
                return place

        # Cache miss or expired — fetch from DB
        place = self.knowledge_repo.get_place_detail(place_id)
        if place is not None:
            PlaceQAService._place_cache[place_id] = (place, now)
            # Evict oldest entries if cache is too large
            if len(PlaceQAService._place_cache) > self._PLACE_CACHE_MAX_SIZE:
                oldest_key = next(iter(PlaceQAService._place_cache))
                del PlaceQAService._place_cache[oldest_key]
        return place

    # Session Management
    def _generate_title_from_question(self, question: str) -> str:
        title = question.split("\n")[0][:50]
        if len(question) > 50:
            title += "..."
        return title or "New Q&A"

    def _format_conversation_history(self, messages: List) -> str:
        if not messages:
            return ""
        history_lines = ["--- Previous Conversation ---"]
        for msg in messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            history_lines.append(f"{role_label}: {msg.content}")
        history_lines.append("--- End Previous Conversation ---\n")
        return "\n".join(history_lines)

    async def list_sessions(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        place_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "last_message",
    ) -> Tuple[List[PlaceQASessionListItem], int, bool]:
        logger.info(
            "Listing sessions — user_id: %s, page: %s, place_id: %s, search: %r",
            user_id,
            page,
            place_id,
            search,
        )

        offset = (page - 1) * page_size
        sessions, total_count = self.qa_repo.list_sessions(
            user_id=user_id,
            place_id=place_id,
            search=search,
            sort_by=sort_by,
            limit=page_size,
            offset=offset,
        )

        has_next = (offset + page_size) < total_count

        # Enrich each session with place info + message preview
        session_items: List[PlaceQASessionListItem] = []
        for session in sessions:
            place_info = None
            if session.place_id:
                place_detail = self._get_cached_place(session.place_id)
                if place_detail:
                    place_info = PlaceInfo(
                        place_id=session.place_id,
                        name=place_detail.display_name,
                        address=place_detail.formatted_address,
                    )

            message_count = self.qa_repo.count_session_messages(session.id)
            last_message = self.qa_repo.get_last_message_preview(session.id)
            if last_message and len(last_message) > 100:
                last_message = last_message[:100] + "..."

            session_items.append(
                PlaceQASessionListItem(
                    session_id=session.id,
                    place=place_info,
                    title=session.title,
                    last_message=last_message,
                    message_count=message_count,
                    last_message_at=session.last_message_at,
                    created_at=session.created_at,
                )
            )

        logger.info(
            "Found %d sessions (total: %d, has_next: %s)",
            len(session_items),
            total_count,
            has_next,
        )

        return session_items, total_count, has_next

    async def get_session_detail(
        self,
        session_id: str,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[Optional[Any], int, bool]:
        """Get a session with paginated messages."""
        offset = (page - 1) * page_size
        session = self.qa_repo.get_session_with_messages(
            session_id=session_id,
            user_id=user_id,
            limit=page_size,
            offset=offset,
        )

        if not session:
            return None, 0, False

        total_messages = self.qa_repo.count_session_messages(session_id)
        has_next = (offset + page_size) < total_messages
        return session, total_messages, has_next

    async def delete_session(self, session_id: str, user_id: int) -> str:
        """Soft delete a session. Returns the deleted session_id."""
        session = self.qa_repo.get_session(session_id=session_id, user_id=user_id)
        if not session:
            raise NotFoundError(f"Session {session_id} not found or access denied")

        self.qa_repo.delete_session(session)
        self.db.commit()
        logger.info("Deleted session %s for user %s", session_id, user_id)
        return session_id

    async def bulk_delete_sessions(
        self, session_ids: List[str], user_id: int
    ) -> List[str]:
        """Bulk soft delete sessions. Returns list of deleted IDs."""
        deleted_ids = self.qa_repo.bulk_delete_sessions(session_ids, user_id)
        self.db.commit()
        logger.info("Bulk deleted %d sessions for user %s", len(deleted_ids), user_id)
        return deleted_ids

    async def update_session(
        self,
        session_id: str,
        user_id: int,
        title: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> Optional[Any]:
        """Update session metadata (e.g. rename title, archive)."""
        session = self.qa_repo.get_session(session_id=session_id, user_id=user_id)
        if not session:
            raise NotFoundError(f"Session {session_id} not found or access denied")

        if title:
            session = self.qa_repo.update_session_title(session, title)

        if archived is not None:
            session.is_deleted = archived
            self.db.flush()

        self.db.commit()
        self.db.refresh(session)
        return session

    # ------------------------------------------------------------------
    # Internal: best-effort audit persistence (never crashes the request)
    # ------------------------------------------------------------------

    def _persist_audit(
        self,
        *,
        user_id: int,
        place_id: str,
        question_text: str,
        knowledge_available: bool,
        pinecone_matches: int,
        answer_text: str,
        confidence_score: Optional[float],
        answer_source: str,
        grounding_chunks: Optional[List[Dict[str, Any]]],
        context_tokens: Optional[int],
        model_used: str,
        latency_ms: int,
        session_id: Optional[str] = None,
    ) -> None:
        try:
            q_row = self.qa_repo.create_question(
                user_id=user_id,
                place_id=place_id,
                question_text=question_text,
                knowledge_available=knowledge_available,
                pinecone_matches=pinecone_matches,
                session_id=session_id,
            )
            self.qa_repo.create_answer_log(
                question_id=q_row.id,
                user_id=user_id,
                place_id=place_id,
                answer_text=answer_text,
                confidence_score=confidence_score,
                answer_source=answer_source,
                grounding_chunks=grounding_chunks,
                context_tokens=context_tokens,
                model_used=model_used,
                latency_ms=latency_ms,
                session_id=session_id,
            )
            self.db.commit()
        except Exception as exc:
            logger.error(
                "PlaceQA audit persist failed (user=%s place=%s session=%s): %s",
                user_id,
                place_id,
                session_id,
                exc,
                extra={
                    "metric": "placeqa.audit_failure",
                    "user_id": user_id,
                    "place_id": place_id,
                    "session_id": session_id,
                    "error": str(exc),
                },
            )
            # Track failure count via log-based metric — monitor logs for
            # sudden increases in placeqa.audit_failure which may indicate
            # a systemic issue with the audit pipeline.
            self.db.rollback()

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    async def answer_question(
        self,
        place_id: str,
        request: PlaceQuestionRequest,
        user_id: int,
    ) -> PlaceQuestionResponse:

        start_time = time.monotonic()
        model_used = settings.OPENAI_CHAT_MODEL

        logger.info(
            "PlaceQA — user_id: %s, place_id: %s, question: %r, session_id: %s",
            user_id,
            place_id,
            request.question,
            request.session_id,
        )

        # ----------------------------------------------------------
        # Step 0 — Credit check (before any expensive work)
        # ----------------------------------------------------------
        await CreditService.check_balance(self.db, user_id, self.CHAT_COST)

        # Step 1 — Session Management
        session = None
        is_new_session = False
        conversation_history = []

        if request.session_id:
            session = self.qa_repo.get_session(
                session_id=request.session_id,
                user_id=user_id,
            )
            if session:
                logger.info("Continuing existing session %s", request.session_id)
                conversation_history = self.qa_repo.get_recent_messages(
                    session_id=session.id,
                    limit=10,
                )
            else:
                # BUG FIX: Return a clear error when session_id is provided but not found,
                # instead of silently creating a new session (which would lose continuity).
                raise NotFoundError(
                    f"Session {request.session_id} not found or access denied"
                )

        if not session:
            current_count = self.qa_repo.count_user_sessions(user_id)
            if current_count >= settings.MAX_SESSIONS_PER_USER:
                raise BadRequestError(
                    f"Maximum session limit ({settings.MAX_SESSIONS_PER_USER}) reached. "
                    "Please delete old sessions before creating new ones."
                )
            title = self._generate_title_from_question(request.question)
            session = self.qa_repo.create_session(
                user_id=user_id,
                place_id=place_id,
                title=title,
            )
            self.db.flush()
            is_new_session = True
            logger.info("Created new session %s — title: %s", session.id, title)

        # Step 2 — Load place from DB (cached)
        place = self._get_cached_place(place_id)
        if place is None:
            logger.warning(
                "PlaceQA blocked — place_id %s not in DB. "
                "Call GET /api/v1/places/{place_id}/details first.",
                place_id,
            )
            raise PlaceDetailNotFoundError(place_id)

        # Step 3 — Check knowledge sync state
        sync_record = self.knowledge_repo.get_sync_record(place_id)
        knowledge_available = (
            sync_record is not None and sync_record.sync_status == "synced"
        )

        # Step 4 — Embed the question
        query_vector: List[float] = []
        pinecone_matches_list: List[Dict[str, Any]] = []

        if knowledge_available:
            try:
                query_vector = await self.openai_client.embed_single(request.question)
            except Exception as exc:
                logger.warning(
                    "PlaceQA embed failed for %s, falling back: %s", place_id, exc
                )
                knowledge_available = False

        # Step 5 — Query Pinecone
        if knowledge_available and query_vector:
            try:
                pinecone_matches_list = await self.pinecone_client.query_vectors(
                    place_id=place_id,
                    query_vector=query_vector,
                    top_k=request.top_k,
                    include_metadata=True,
                )
            except Exception as exc:
                logger.warning(
                    "PlaceQA Pinecone query failed for %s, falling back: %s",
                    place_id,
                    exc,
                )
                pinecone_matches_list = []

        # Step 6 — Filter by similarity threshold + token budget
        accepted_matches = [
            m
            for m in pinecone_matches_list
            if (m.get("score") or 0.0) >= _SIMILARITY_THRESHOLD
        ]
        accepted_matches = sorted(
            accepted_matches, key=lambda m: m.get("score", 0.0), reverse=True
        )

        max_context_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        structured_block = _build_structured_facts_block(place)
        structured_tokens = _estimate_tokens(structured_block)

        conversation_context = ""
        if conversation_history:
            conversation_context = self._format_conversation_history(
                conversation_history
            )
        conversation_tokens = _estimate_tokens(conversation_context)

        available_for_chunks = (
            max_context_tokens - structured_tokens - conversation_tokens - 200
        )

        trimmed_matches = []
        cumulative_tokens = 0
        for match in accepted_matches:
            text = match.get("metadata", {}).get("text", "")
            chunk_tokens = _estimate_tokens(text)
            if cumulative_tokens + chunk_tokens <= available_for_chunks:
                trimmed_matches.append(match)
                cumulative_tokens += chunk_tokens
            else:
                break
        accepted_matches = trimmed_matches

        # Step 7 — Assemble context
        context_parts: List[str] = []
        grounding_chunks_for_log: List[Dict[str, Any]] = []
        grounding_fragments: List[GroundingFragment] = []

        if conversation_context:
            context_parts.append(conversation_context)

        context_parts.append("--- Structured Information ---")
        context_parts.append(structured_block)

        if accepted_matches:
            context_parts.append("\n--- Knowledge Base (Retrieved Sections) ---")
            for match in accepted_matches:
                meta = match.get("metadata", {})
                section = meta.get("section", "unknown")
                text = meta.get("text", "")
                score = round(float(match.get("score", 0.0)), 4)
                if text.strip():
                    context_parts.append(f"\n[{section.upper()}]\n{text}")
                    grounding_chunks_for_log.append(
                        {"section": section, "text": text, "score": score}
                    )
                    grounding_fragments.append(
                        GroundingFragment(
                            section=section,
                            text=text[:300],
                            similarity_score=score,
                            source_type="pinecone",
                        )
                    )

        grounding_fragments.insert(
            0,
            GroundingFragment(
                section="structured_db",
                text=structured_block[:300],
                similarity_score=1.0,
                source_type="structured_db",
            ),
        )

        context_block = "\n".join(context_parts)
        context_tokens = _estimate_tokens(context_block)

        # Step 8 — Build system prompt
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context_block=context_block)

        # Step 9 — Call OpenAI
        answer = await self.openai_client.chat_completion(
            system_prompt=system_prompt,
            user_message=request.question,
            temperature=0.7,
            max_tokens=800,
        )

        # Compute confidence + answer source
        accepted_scores = [float(m.get("score", 0.0)) for m in accepted_matches]
        confidence_score = _compute_confidence(accepted_scores)

        if not knowledge_available:
            answer_source = AnswerSource.FALLBACK
        elif accepted_matches:
            answer_source = AnswerSource.RAG
        else:
            answer_source = AnswerSource.STRUCTURED_ONLY

        latency_ms = int((time.monotonic() - start_time) * 1000)

        try:
            await CreditService.deduct(self.db, user_id, self.CHAT_COST)
            self.qa_repo.create_message(
                session_id=session.id,
                role="user",
                content=request.question,
                token_count=_estimate_tokens(request.question),
            )

            self.qa_repo.create_message(
                session_id=session.id,
                role="assistant",
                content=answer,
                token_count=_estimate_tokens(answer),
                metadata_json={
                    "answer_source": answer_source,
                    "confidence_score": confidence_score,
                    "pinecone_matches": len(accepted_matches),
                },
            )

            self.db.flush()
            self.qa_repo.update_session_timestamp(session)
            self.db.commit()
            logger.info(
                "Committed credits deduction + messages for session %s (user %s)",
                session.id,
                user_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to commit credits/messages for session %s: %s", session.id, exc
            )
            self.db.rollback()
            raise

        # Best-effort audit (separate commit, after main commit)
        self._persist_audit(
            user_id=user_id,
            place_id=place_id,
            question_text=request.question,
            knowledge_available=knowledge_available,
            pinecone_matches=len(accepted_matches),
            answer_text=answer,
            confidence_score=confidence_score,
            answer_source=answer_source,
            grounding_chunks=grounding_chunks_for_log or None,
            context_tokens=context_tokens,
            model_used=model_used,
            latency_ms=latency_ms,
            session_id=session.id,
        )

        # Return response
        metadata = TechnicalMetadata(
            answer_source=answer_source,
            confidence_score=confidence_score,
            knowledge_synced=knowledge_available,
            pinecone_matches=len(accepted_matches),
            model_used=model_used,
            context_tokens=context_tokens,
            grounding_fragments=grounding_fragments if grounding_fragments else None,
        )

        response_data: Dict[str, Any] = {
            "success": True,
            "session_id": session.id,
            "answer": answer,
            "is_new_session": is_new_session,
            "metadata": metadata,
        }

        if is_new_session:
            response_data["title"] = session.title

        return PlaceQuestionResponse(**response_data)

    # ------------------------------------------------------------------
    # Streaming answer — token-by-token via async generator
    # ------------------------------------------------------------------

    async def stream_answer(
        self,
        place_id: str,
        question: str,
        user_id: int,
        session_id: Optional[str] = None,
        top_k: int = 5,
    ) -> AsyncGenerator[str, None]:
        """
        Like answer_question() but yields tokens as they arrive from OpenAI.

        Yields JSON-encoded control events and content tokens:
        - {"type": "metadata", "session_id": ..., "is_new_session": ..., "place_id": ...}
        - {"type": "token", "content": "..."}
        - {"type": "done", "title": ..., "metadata": {...}}
        """
        start_time = time.monotonic()
        model_used = settings.OPENAI_CHAT_MODEL

        logger.info(
            "PlaceQA stream — user_id: %s, place_id: %s, question: %r, "
            "session_id: %s",
            user_id,
            place_id,
            question,
            session_id,
        )

        # Step 0 — Credit check
        await CreditService.check_balance(self.db, user_id, self.CHAT_COST)

        # Step 1 — Session Management
        sess = None
        is_new_session = False
        conversation_history = []

        if session_id:
            sess = self.qa_repo.get_session(
                session_id=session_id,
                user_id=user_id,
            )
            if sess:
                logger.info("Continuing existing session %s", session_id)
                conversation_history = self.qa_repo.get_recent_messages(
                    session_id=sess.id,
                    limit=10,
                )
            else:
                logger.warning(
                    "Session %s not found for user %s — creating new",
                    session_id,
                    user_id,
                )

        if not sess:
            current_count = self.qa_repo.count_user_sessions(user_id)
            if current_count >= settings.MAX_SESSIONS_PER_USER:
                raise BadRequestError(
                    f"Maximum session limit ({settings.MAX_SESSIONS_PER_USER}) reached. "
                    "Please delete old sessions before creating new ones."
                )
            title = self._generate_title_from_question(question)
            sess = self.qa_repo.create_session(
                user_id=user_id,
                place_id=place_id,
                title=title,
            )
            self.db.flush()
            is_new_session = True
            logger.info("Created new session %s — title: %s", sess.id, title)

        # Yield metadata immediately
        yield json.dumps(
            {
                "type": "metadata",
                "session_id": sess.id,
                "is_new_session": is_new_session,
                "place_id": place_id,
            }
        )

        # Step 2 — Load place from DB (cached)
        place = self._get_cached_place(place_id)
        if place is None:
            logger.warning(
                "PlaceQA stream blocked — place_id %s not in DB",
                place_id,
            )
            raise PlaceDetailNotFoundError(place_id)

        # Step 3-7 — Build context (same as answer_question)
        sync_record = self.knowledge_repo.get_sync_record(place_id)
        knowledge_available = (
            sync_record is not None and sync_record.sync_status == "synced"
        )

        query_vector: List[float] = []
        pinecone_matches_list: List[Dict[str, Any]] = []

        if knowledge_available:
            try:
                query_vector = await self.openai_client.embed_single(question)
            except Exception as exc:
                logger.warning(
                    "PlaceQA stream embed failed for %s, falling back: %s",
                    place_id,
                    exc,
                )
                knowledge_available = False

        if knowledge_available and query_vector:
            try:
                pinecone_matches_list = await self.pinecone_client.query_vectors(
                    place_id=place_id,
                    query_vector=query_vector,
                    top_k=top_k,
                    include_metadata=True,
                )
            except Exception as exc:
                logger.warning(
                    "PlaceQA stream Pinecone query failed for %s, fallback: %s",
                    place_id,
                    exc,
                )
                pinecone_matches_list = []

        accepted_matches = [
            m
            for m in pinecone_matches_list
            if (m.get("score") or 0.0) >= _SIMILARITY_THRESHOLD
        ]
        accepted_matches = sorted(
            accepted_matches, key=lambda m: m.get("score", 0.0), reverse=True
        )

        max_context_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        structured_block = _build_structured_facts_block(place)
        structured_tokens = _estimate_tokens(structured_block)

        conversation_context = ""
        if conversation_history:
            conversation_context = self._format_conversation_history(
                conversation_history
            )
        conversation_tokens = _estimate_tokens(conversation_context)

        available_for_chunks = (
            max_context_tokens - structured_tokens - conversation_tokens - 200
        )

        trimmed_matches = []
        cumulative_tokens = 0
        for match in accepted_matches:
            text = match.get("metadata", {}).get("text", "")
            chunk_tokens = _estimate_tokens(text)
            if cumulative_tokens + chunk_tokens <= available_for_chunks:
                trimmed_matches.append(match)
                cumulative_tokens += chunk_tokens
            else:
                break
        accepted_matches = trimmed_matches

        # Assemble context
        context_parts: List[str] = []
        grounding_chunks_for_log: List[Dict[str, Any]] = []

        if conversation_context:
            context_parts.append(conversation_context)

        context_parts.append("--- Structured Information ---")
        context_parts.append(structured_block)

        if accepted_matches:
            context_parts.append("\n--- Knowledge Base (Retrieved Sections) ---")
            for match in accepted_matches:
                meta = match.get("metadata", {})
                section = meta.get("section", "unknown")
                text = meta.get("text", "")
                score = round(float(match.get("score", 0.0)), 4)
                if text.strip():
                    context_parts.append(f"\n[{section.upper()}]\n{text}")
                    grounding_chunks_for_log.append(
                        {"section": section, "text": text, "score": score}
                    )

        context_block = "\n".join(context_parts)
        context_tokens = _estimate_tokens(context_block)

        # Build system prompt
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context_block=context_block)

        # Compute source metadata
        accepted_scores = [float(m.get("score", 0.0)) for m in accepted_matches]
        confidence_score = _compute_confidence(accepted_scores)

        if not knowledge_available:
            answer_source = AnswerSource.FALLBACK
        elif accepted_matches:
            answer_source = AnswerSource.RAG
        else:
            answer_source = AnswerSource.STRUCTURED_ONLY

        # Step 9 — Stream from OpenAI
        full_answer_parts: List[str] = []
        try:
            async for token in self.openai_client.stream_chat_completion(
                system_prompt=system_prompt,
                user_message=question,
                temperature=0.7,
                max_tokens=800,
            ):
                full_answer_parts.append(token)
                yield json.dumps({"type": "token", "content": token})
        except Exception:
            logger.exception("OpenAI streaming failed during place QA")
            raise

        answer = "".join(full_answer_parts)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Step 10 — Persist messages + deduct credits
        try:
            await CreditService.deduct(self.db, user_id, self.CHAT_COST)
            self.qa_repo.create_message(
                session_id=sess.id,
                role="user",
                content=question,
                token_count=_estimate_tokens(question),
            )
            self.qa_repo.create_message(
                session_id=sess.id,
                role="assistant",
                content=answer,
                token_count=_estimate_tokens(answer),
                metadata_json={
                    "answer_source": answer_source,
                    "confidence_score": confidence_score,
                    "pinecone_matches": len(accepted_matches),
                },
            )
            self.db.flush()
            self.qa_repo.update_session_timestamp(sess)
            self.db.commit()
        except Exception as exc:
            logger.error(
                "Failed to commit credits/messages for session %s: %s",
                sess.id,
                exc,
            )
            self.db.rollback()
            raise

        # Best-effort audit
        self._persist_audit(
            user_id=user_id,
            place_id=place_id,
            question_text=question,
            knowledge_available=knowledge_available,
            pinecone_matches=len(accepted_matches),
            answer_text=answer,
            confidence_score=confidence_score,
            answer_source=answer_source,
            grounding_chunks=grounding_chunks_for_log or None,
            context_tokens=context_tokens,
            model_used=model_used,
            latency_ms=latency_ms,
            session_id=sess.id,
        )

        yield json.dumps(
            {
                "type": "done",
                "title": sess.title if is_new_session else None,
                "metadata": {
                    "answer_source": answer_source,
                    "confidence_score": confidence_score,
                    "knowledge_synced": knowledge_available,
                    "pinecone_matches": len(accepted_matches),
                    "context_tokens": context_tokens,
                },
            }
        )
