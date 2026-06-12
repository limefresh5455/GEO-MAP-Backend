"""
Pydantic schemas for the Place Q&A layer.

Covers:
  POST /api/v1/places/{place_id}/question
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Answer source constants
# ---------------------------------------------------------------------------

class AnswerSource:
    RAG             = "rag"              # Pinecone retrieval + structured facts
    STRUCTURED_ONLY = "structured_only" # PG structured data only (no Pinecone match)
    FALLBACK        = "fallback"         # No knowledge synced — minimal answer


# ---------------------------------------------------------------------------
# Supporting evidence fragment — shown to the frontend for transparency
# ---------------------------------------------------------------------------

class GroundingFragment(BaseModel):
    """
    A single supporting fact chunk used to ground the answer.
    Returned to the frontend so it can render source attribution.
    """
    section: str                    # which document section this came from
    text: str                       # the chunk text used as context
    similarity_score: float         # Pinecone cosine similarity (0.0–1.0)
    source_type: str                # "pinecone" | "structured_db"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class PlaceQuestionRequest(BaseModel):
    """
    Payload for POST /api/v1/places/{place_id}/question.
    """

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description=(
            "Natural-language question about the selected place. "
            "Examples: 'Is this place open now?', "
            "'Does it have parking?', "
            "'What do reviews say about the food?'"
        ),
    )
    top_k: int = Field(
        default=4,
        ge=1,
        le=7,
        description=(
            "Number of Pinecone knowledge chunks to retrieve for context (1–7). "
            "Higher values give broader context at the cost of token budget."
        ),
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class PlaceQuestionResponse(BaseModel):
    """
    Standard response envelope for POST /api/v1/places/{place_id}/question.
    """

    success: bool
    place_id: str
    question: str
    answer: str

    # Grounding metadata — helps the frontend show "based on" attribution
    answer_source: str              # "rag" | "structured_only" | "fallback"
    confidence_score: Optional[float] = None   # 0.0–1.0 from Pinecone scores
    grounding_fragments: Optional[List[GroundingFragment]] = None

    # Context quality signals
    knowledge_synced: bool          # was the place indexed in Pinecone?
    pinecone_matches: int           # how many chunks were retrieved

    # Generation metadata
    model_used: str
    context_tokens: Optional[int] = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
