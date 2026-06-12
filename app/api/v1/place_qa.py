"""
Place Q&A API — Phase 4.

Routes
------
POST /api/v1/places/{place_id}/question
    Natural-language question answered from the place's indexed knowledge.

All routes require a valid Bearer token.
The place_id must exist in place_details AND ideally be knowledge-synced.
If not synced, the endpoint degrades gracefully to a structured-data-only answer.
"""

import logging

from fastapi import APIRouter, Depends, Path

from app.dependencies.auth import get_current_user
from app.dependencies.place_qa import get_place_qa_service
from app.models.user import User
from app.schemas.place_qa import PlaceQuestionRequest, PlaceQuestionResponse
from app.services.place_qa_service import PlaceQAService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["Place Q&A"])


@router.post("/{place_id}/question", response_model=PlaceQuestionResponse)
async def ask_place_question(
    place_id: str = Path(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Google place ID of the place to ask about. "
            "Must exist in the local database (call Details API first). "
            "Should be knowledge-synced for best answers (call knowledge-sync first)."
        ),
    ),
    payload: PlaceQuestionRequest = ...,
    current_user: User = Depends(get_current_user),
    service: PlaceQAService = Depends(get_place_qa_service),
) -> PlaceQuestionResponse:
    """
    Ask a natural-language question about a specific place.

    **Examples of questions:**
    - "Is this place open now?"
    - "Does it have parking?"
    - "Is it good for families?"
    - "What are customers saying about the food?"
    - "How much does it cost?"
    - "Is it wheelchair accessible?"
    - "What are the opening hours on weekends?"

    **How it works (Geo Dynamic RAG pipeline):**
    1. Load the place's structured profile from PostgreSQL.
    2. Check whether the place has been knowledge-synced (Phase 3).
    3. Embed the question via OpenAI `text-embedding-3-small`.
    4. Query the place's Pinecone namespace for the most relevant knowledge chunks.
    5. Filter chunks below the 0.30 cosine similarity threshold.
    6. Build a context package: structured facts (always) + retrieved chunks.
    7. Send context + question to OpenAI `gpt-4o-mini`.
    8. Return the grounded answer with supporting evidence fragments.

    **Answer sources:**
    - `rag` — Pinecone retrieval succeeded; answer grounded on indexed knowledge.
    - `structured_only` — No relevant Pinecone matches; answer from PostgreSQL data.
    - `fallback` — Place not yet knowledge-synced; minimal answer from name/address.

    **Grounding transparency:**
    The response includes `grounding_fragments` — the exact knowledge chunks
    used to construct the answer — so the frontend can show source attribution.

    **Prerequisites:**
    - `GET /api/v1/places/{place_id}/details` must have been called first.
    - `POST /api/v1/places/{place_id}/knowledge-sync` recommended for full RAG.

    **Required:** `Authorization: Bearer <token>`
    """
    logger.info(
        "Place Q&A — user_id: %s, place_id: %s, question: %r",
        current_user.id,
        place_id,
        payload.question,
    )

    return await service.answer_question(
        place_id=place_id,
        request=payload,
        user_id=current_user.id,
    )
