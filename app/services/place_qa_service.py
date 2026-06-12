"""
PlaceQAService — Geo Dynamic RAG pipeline for place-scoped Q&A.

Full pipeline for POST /api/v1/places/{place_id}/question:

  Step 1  Load place details from PostgreSQL.
          → Raises PlaceDetailNotFoundError if not yet fetched.
  Step 2  Load knowledge sync state from place_knowledge_sync.
          → Determines whether Pinecone retrieval is available.
  Step 3  Embed the user's question via OpenAI text-embedding-3-small.
  Step 4  Query Pinecone namespace "place_{place_id}" for top-k matches.
          → If no sync record or status != "synced": skip to structured-only path.
  Step 5  Filter matches below similarity threshold (0.30 cosine).
  Step 6  Build a structured facts block from PostgreSQL columns.
          → Always included regardless of Pinecone result count.
  Step 7  Assemble context package: structured block + retrieved chunks.
  Step 8  Build system prompt that binds the model to the context.
  Step 9  Call OpenAI gpt-4o-mini with the context + question.
  Step 10 Compute confidence score from Pinecone similarity scores.
  Step 11 Persist question + answer logs to PostgreSQL.
  Step 12 Commit.
  Step 13 Return PlaceQuestionResponse.

Answer source labels
--------------------
  "rag"             — Pinecone retrieval succeeded, answer grounded on chunks
  "structured_only" — Pinecone returned 0 useful matches; answer from PG data
  "fallback"        — place not yet knowledge-synced; answer from name/address only

Design rules
------------
- The answer NEVER invents facts. The system prompt explicitly instructs the
  model to say "I don't have that information" rather than hallucinate.
- Context is always bounded to one place (namespace isolation in Pinecone).
- Confidence score is the mean cosine similarity of accepted Pinecone matches,
  scaled to 0.0–1.0. Returns None on structured_only / fallback paths.
- Audit writes (question + answer log) are in a finally-like block — if they
  fail, the error is logged and swallowed so the user still gets their answer.
- Latency is measured end-to-end from question embed to answer return.
"""

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
_SYSTEM_PROMPT_TEMPLATE = """You are a helpful local guide assistant answering questions about a specific place.

You MUST answer ONLY from the information provided in the PLACE CONTEXT below.
If the context does not contain enough information to answer the question, say:
"I don't have that information about this place."
Do NOT invent, guess, or use any outside knowledge.
Be concise. Answer in 1–4 sentences unless a list is clearly more appropriate.

PLACE CONTEXT:
{context_block}"""

# Approximate characters per token (rough estimate for token budget)
_CHARS_PER_TOKEN = 4


def _build_structured_facts_block(place) -> str:
    """
    Build a short structured text block from PostgreSQL columns.
    Always included in the context — provides a reliable baseline even
    when Pinecone retrieval returns nothing.
    """
    lines = []

    if place.display_name:
        lines.append(f"Place name: {place.display_name}")
    if place.formatted_address:
        lines.append(f"Address: {place.formatted_address}")
    if place.primary_type:
        lines.append(f"Category: {place.primary_type}")

    if place.rating is not None:
        lines.append(f"Rating: {place.rating}/5.0")
    if place.user_rating_count is not None:
        lines.append(f"Total reviews: {place.user_rating_count}")

    if place.business_status:
        label = place.business_status.replace("_", " ").capitalize()
        lines.append(f"Status: {label}")

    if place.open_now is not None:
        lines.append(f"Open now: {'Yes' if place.open_now else 'No'}")

    if place.opening_hours and isinstance(place.opening_hours, dict):
        weekdays = place.opening_hours.get("weekday_descriptions") or []
        if weekdays:
            lines.append("Opening hours:")
            for day in weekdays:
                lines.append(f"  {day}")

    if place.international_phone_number:
        lines.append(f"Phone: {place.international_phone_number}")
    if place.website_uri:
        lines.append(f"Website: {place.website_uri}")
    if place.google_maps_uri:
        lines.append(f"Google Maps: {place.google_maps_uri}")

    if place.price_level:
        label = place.price_level.replace("PRICE_LEVEL_", "").capitalize()
        lines.append(f"Price level: {label}")

    if place.wheelchair_accessible_entrance is not None:
        lines.append(
            f"Wheelchair accessible: "
            f"{'Yes' if place.wheelchair_accessible_entrance else 'No'}"
        )

    if place.editorial_summary:
        lines.append(f"About: {place.editorial_summary}")

    return "\n".join(lines)


def _compute_confidence(scores: List[float]) -> Optional[float]:
    """
    Mean of accepted Pinecone cosine similarity scores, rounded to 3dp.
    Returns None if the list is empty.
    """
    if not scores:
        return None
    return round(sum(scores) / len(scores), 3)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate — character count / 4."""
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
        # Step 6 — Build structured facts block (always present)
        # ----------------------------------------------------------
        structured_block = _build_structured_facts_block(place)

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
        # ----------------------------------------------------------
        answer = await self.openai_client.chat_completion(
            system_prompt=system_prompt,
            user_message=request.question,
            temperature=0.2,
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
