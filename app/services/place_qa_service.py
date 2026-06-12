import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
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
)

logger = logging.getLogger(__name__)

# Pinecone similarity scores below this threshold are excluded from context.
# Cosine similarity for text-embedding-3-small: 0.30 ≈ weakly related.
_SIMILARITY_THRESHOLD = 0.30

# System prompt template — {context_block} is replaced at runtime
# ENHANCED: More human-like, conversational responses with better context awareness
_SYSTEM_PROMPT_TEMPLATE = """You are a friendly and knowledgeable local guide who helps people discover and learn about places in their area. Your goal is to provide helpful, accurate, and conversational answers that feel natural and human.

**LANGUAGE REQUIREMENT:**
- ALWAYS respond in ENGLISH, regardless of the language used in the question
- If the user asks in Hindi, Hinglish, or any other language, translate your answer to English
- Use clear, simple English that's easy to understand

**Response Guidelines:**

1. **BE CONVERSATIONAL**: Write like you're talking to a friend, not a robot.
   - ✅ Good: "Yes, they're open right now! They close at 9 PM today."
   - ❌ Bad: "Status: Open. Closing time: 21:00."

2. **BE HELPFUL**: If the question needs context, provide it naturally.
   - Example: "They have a 4.2 rating with over 200 reviews, which is pretty good for this area!"

3. **BE HONEST**: If information is missing, acknowledge it kindly and suggest alternatives.
   - ✅ Good: "I don't see specific parking information, but based on the location in downtown, there's likely street parking nearby."
   - ❌ Bad: "I don't have that information about this place."

4. **USE NATURAL LANGUAGE**:
   - Instead of "Rating: 4.2/5.0" → say "It has a solid 4.2-star rating"
   - Instead of "Open now: Yes" → say "Yes, they're open right now"
   - Instead of "Wheelchair accessible: Yes" → say "Good news - this place is wheelchair accessible"

5. **BE SPECIFIC**: When you have details, share them.
   - ✅ "They serve breakfast from 7 AM and have vegetarian options available."
   - ❌ "They serve food."

6. **SYNTHESIZE INFORMATION**: Connect related facts to give better answers.
   - Question: "Is it good for families?"
   - ✅ Good: "Yes! They have a children's menu, outdoor seating, and many reviews mention it's family-friendly. Plus, the atmosphere is casual and relaxed."
   - ❌ Bad: "Yes, good for children."

7. **HANDLE SENTIMENT**: Extract sentiment from reviews naturally.
   - ✅ "People love the coffee here! Several reviews specifically mention the great espresso and friendly baristas."
   - ❌ "Reviews mention coffee and staff."

**CRITICAL RULES:**
- ALWAYS respond in ENGLISH only
- Answer ONLY from the PLACE CONTEXT below
- DO NOT invent facts, prices, or details not in the context
- If unsure, say so - but in a friendly way
- Keep answers concise (2-4 sentences) unless a list or detailed explanation is clearly needed
- Use conversational contractions (they're, it's, you'll, etc.)

**PLACE CONTEXT:**
{context_block}

Now, answer the user's question in ENGLISH in a friendly, natural, and helpful way based on this context."""

# B051 FIX: Changed from 4 to 3 chars per token for safer budget control.
# Approximate characters per token (rough estimate for token budget)
# The tighter ratio (3 instead of 4) provides a safety margin to prevent
# exceeding the OpenAI context window, especially for technical text with
# special characters, JSON, or non-ASCII content that tokenizes less efficiently.
_CHARS_PER_TOKEN = 3


def _build_structured_facts_block(place) -> str:
    """
    Build a short structured text block from PostgreSQL columns.
    Always included in the context — provides a reliable baseline even
    when Pinecone retrieval returns nothing.
    
    ENHANCED: More natural language formatting for better GPT comprehension
    """
    sections = []

    # Basic info section
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

    # Ratings and popularity
    rating_info = []
    if place.rating is not None:
        rating_info.append(f"Rating: {place.rating} out of 5 stars")
    if place.user_rating_count is not None:
        rating_info.append(f"based on {place.user_rating_count} reviews")
    if rating_info:
        sections.append(" ".join(rating_info) + ".")

    # Business status
    if place.business_status:
        status = place.business_status.replace("_", " ").lower()
        if status == "operational":
            sections.append("The business is currently operational.")
        else:
            sections.append(f"Business status: {status}.")

    # Current status
    if place.open_now is not None:
        if place.open_now:
            sections.append("Currently OPEN for customers.")
        else:
            sections.append("Currently CLOSED.")

    # Operating hours
    if place.opening_hours and isinstance(place.opening_hours, dict):
        weekdays = place.opening_hours.get("weekday_descriptions") or []
        if weekdays:
            sections.append("Operating hours:")
            for day in weekdays:
                sections.append(f"  • {day}")

    # Contact and web presence
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

    # Price level (with human interpretation)
    if place.price_level:
        price = place.price_level.replace("PRICE_LEVEL_", "").lower()
        price_descriptions = {
            "free": "Free admission or no cost",
            "inexpensive": "Budget-friendly (₹)",
            "moderate": "Moderately priced (₹₹)",
            "expensive": "Upscale pricing (₹₹₹)",
            "very_expensive": "Premium/luxury pricing (₹₹₹₹)"
        }
        price_text = price_descriptions.get(price, price.capitalize())
        sections.append(f"Price range: {price_text}")

    # Accessibility
    if place.wheelchair_accessible_entrance is not None:
        if place.wheelchair_accessible_entrance:
            sections.append("♿ Wheelchair accessible entrance available.")
        else:
            sections.append("Note: No wheelchair accessible entrance.")

    # About / Editorial
    if place.editorial_summary:
        sections.append(f"\nAbout this place: {place.editorial_summary}")

    return "\n".join(sections)


def _compute_confidence(scores: List[float]) -> Optional[float]:
    """
    Mean of accepted Pinecone cosine similarity scores, rounded to 3dp.
    Returns None if the list is empty.
    """
    if not scores:
        return None
    return round(sum(scores) / len(scores), 3)


def _estimate_tokens(text: str) -> int:
    """
    B051 FIX: Improved token estimation for better budget control.
    
    Rough token estimate using _CHARS_PER_TOKEN ratio (now 3 chars per token).
    GPT models use subword tokenization — this is a conservative approximation.
    
    For production use, consider using the `tiktoken` library for exact counts:
      import tiktoken
      encoding = tiktoken.encoding_for_model("gpt-4")
      return len(encoding.encode(text))
    """
    return max(1, len(text) // _CHARS_PER_TOKEN)


class PlaceQAService:
    """
    Orchestrates the place-scoped RAG question-answering pipeline.
    """

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

    # ------------------------------------------------------------------
    # Internal: audit persistence  (best-effort — never crashes the request)
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
    ) -> None:
        try:
            q_row = self.qa_repo.create_question(
                user_id=user_id,
                place_id=place_id,
                question_text=question_text,
                knowledge_available=knowledge_available,
                pinecone_matches=pinecone_matches,
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
            )
            self.db.commit()
        except Exception as exc:
            logger.error(
                "PlaceQA audit persist failed (user=%s place=%s): %s",
                user_id, place_id, exc,
            )
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
        """
        Answer a natural-language question about one specific place.

        Returns PlaceQuestionResponse.
        Raises PlaceDetailNotFoundError if the place has never been fetched.
        """
        start_time = time.monotonic()
        model_used = settings.OPENAI_CHAT_MODEL

        logger.info(
            "PlaceQA — user_id: %s, place_id: %s, question: %r",
            user_id, place_id, request.question,
        )

        # ----------------------------------------------------------
        # Step 1 — Load place from DB
        # ----------------------------------------------------------
        place = self.knowledge_repo.get_place_detail(place_id)
        if place is None:
            logger.warning(
                "PlaceQA blocked — place_id %s not in DB. "
                "Call GET /api/v1/places/{place_id}/details first.",
                place_id,
            )
            raise PlaceDetailNotFoundError(place_id)

        # ----------------------------------------------------------
        # Step 2 — Check knowledge sync state
        # ----------------------------------------------------------
        sync_record = self.knowledge_repo.get_sync_record(place_id)
        knowledge_available = (
            sync_record is not None
            and sync_record.sync_status == "synced"
        )

        logger.info(
            "PlaceQA — knowledge_available: %s for place_id: %s",
            knowledge_available, place_id,
        )

        # ----------------------------------------------------------
        # Step 3 — Embed the question
        # ----------------------------------------------------------
        query_vector: List[float] = []
        pinecone_matches_list: List[Dict[str, Any]] = []
        accepted_matches: List[Dict[str, Any]] = []

        if knowledge_available:
            try:
                query_vector = await self.openai_client.embed_single(
                    request.question
                )
            except Exception as exc:
                logger.warning(
                    "PlaceQA embed failed for place_id %s, falling back: %s",
                    place_id, exc,
                )
                knowledge_available = False  # degrade gracefully

        # ----------------------------------------------------------
        # Step 4 — Query Pinecone (only if embedding succeeded)
        # ----------------------------------------------------------
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
                    "PlaceQA Pinecone query failed for place_id %s, "
                    "falling back to structured-only: %s",
                    place_id, exc,
                )
                pinecone_matches_list = []

        # ----------------------------------------------------------
        # Step 5 — Filter by similarity threshold
        # ----------------------------------------------------------
        accepted_matches = [
            m for m in pinecone_matches_list
            if (m.get("score") or 0.0) >= _SIMILARITY_THRESHOLD
        ]

        logger.info(
            "PlaceQA — Pinecone: %d total matches, %d above threshold %.2f",
            len(pinecone_matches_list),
            len(accepted_matches),
            _SIMILARITY_THRESHOLD,
        )

        # ----------------------------------------------------------
        # B-050 FIX: Enforce token budget BEFORE building full context
        # Sort matches by score descending, then trim to fit budget
        # ----------------------------------------------------------
        max_context_tokens = settings.OPENAI_MAX_CONTEXT_TOKENS
        
        # Sort by score (best first)
        accepted_matches = sorted(
            accepted_matches, key=lambda m: m.get("score", 0.0), reverse=True
        )
        
        # Build structured facts block (always included)
        structured_block = _build_structured_facts_block(place)
        structured_tokens = _estimate_tokens(structured_block)
        
        # Reserve tokens for structured block + system prompt overhead (~200 tokens)
        available_for_chunks = max_context_tokens - structured_tokens - 200
        
        # Trim chunks to fit budget
        trimmed_matches = []
        cumulative_tokens = 0
        
        for match in accepted_matches:
            meta = match.get("metadata", {})
            text = meta.get("text", "")
            chunk_tokens = _estimate_tokens(text)
            
            if cumulative_tokens + chunk_tokens <= available_for_chunks:
                trimmed_matches.append(match)
                cumulative_tokens += chunk_tokens
            else:
                logger.info(
                    "PlaceQA B-050: Dropped chunk (would exceed budget) — "
                    "score=%.3f, tokens=%d",
                    match.get("score", 0.0), chunk_tokens
                )
                break
        
        accepted_matches = trimmed_matches
        logger.info(
            "PlaceQA B-050: Token budget enforced — kept %d/%d chunks, "
            "total_tokens=%d, budget=%d",
            len(accepted_matches), len(pinecone_matches_list),
            structured_tokens + cumulative_tokens, max_context_tokens
        )

        # ----------------------------------------------------------
        # Step 6 — Build structured facts block (already done above)
        # ----------------------------------------------------------
        # (moved before chunk trimming)

        # ----------------------------------------------------------
        # Step 7 — Assemble context package
        # ----------------------------------------------------------
        context_parts: List[str] = []
        grounding_chunks_for_log: List[Dict[str, Any]] = []
        grounding_fragments: List[GroundingFragment] = []

        # Always lead with structured facts
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
                            text=text[:300],   # truncate for response payload
                            similarity_score=score,
                            source_type="pinecone",
                        )
                    )

        # Add structured block as grounding fragment too
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

        logger.info(
            "PlaceQA — context assembled: ~%d tokens, %d grounding chunks",
            context_tokens, len(accepted_matches),
        )

        # ----------------------------------------------------------
        # Step 8 — Build system prompt
        # ----------------------------------------------------------
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            context_block=context_block
        )

        # ----------------------------------------------------------
        # Step 9 — Call OpenAI Chat Completions
        # ENHANCED: Increased temperature from 0.2 to 0.7 for more natural,
        # human-like conversational responses while maintaining accuracy
        # ----------------------------------------------------------
        answer = await self.openai_client.chat_completion(
            system_prompt=system_prompt,
            user_message=request.question,
            temperature=0.7,  # Increased from 0.2 for more natural responses
            max_tokens=800,
        )

        # ----------------------------------------------------------
        # Step 10 — Compute confidence + determine answer source
        # ----------------------------------------------------------
        accepted_scores = [
            float(m.get("score", 0.0)) for m in accepted_matches
        ]
        confidence_score = _compute_confidence(accepted_scores)

        if not knowledge_available:
            answer_source = AnswerSource.FALLBACK
        elif accepted_matches:
            answer_source = AnswerSource.RAG
        else:
            answer_source = AnswerSource.STRUCTURED_ONLY

        latency_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "PlaceQA complete — place_id: %s, source: %s, "
            "confidence: %s, latency: %dms",
            place_id, answer_source, confidence_score, latency_ms,
        )

        # ----------------------------------------------------------
        # Step 11 & 12 — Persist audit + commit (best-effort)
        # ----------------------------------------------------------
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
        )

        # ----------------------------------------------------------
        # Step 13 — Return response
        # ----------------------------------------------------------
        return PlaceQuestionResponse(
            success=True,
            place_id=place_id,
            question=request.question,
            answer=answer,
            answer_source=answer_source,
            confidence_score=confidence_score,
            grounding_fragments=grounding_fragments if grounding_fragments else None,
            knowledge_synced=knowledge_available,
            pinecone_matches=len(accepted_matches),
            model_used=model_used,
            context_tokens=context_tokens,
        )
