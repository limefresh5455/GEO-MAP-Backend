from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

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
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Your question about the place",
    )
    session_id: Optional[str] = Field(
        default=None,
        min_length=36,
        max_length=36,
        description="UUID v4 session ID to continue conversation (optional)",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of knowledge chunks to retrieve",
    )

    @field_validator("session_id", mode="before")
    @classmethod
    def normalize_session_id(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class TechnicalMetadata(BaseModel):
    """Technical details for debugging (optional, not shown by default)."""
    answer_source: str
    confidence_score: Optional[float] = None
    knowledge_synced: bool
    pinecone_matches: int
    model_used: str
    context_tokens: Optional[int] = None
    grounding_fragments: Optional[List[GroundingFragment]] = None


class PlaceQuestionResponse(BaseModel):
    success: bool = True
    session_id: str
    answer: str

    # Only for new sessions
    title: Optional[str] = None
    is_new_session: bool = False

    # Optional technical details (for debug mode)
    metadata: Optional[TechnicalMetadata] = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Session Management Schemas
# ---------------------------------------------------------------------------

class PlaceQAMessageSchema(BaseModel):
    id: int
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    created_at: datetime
    token_count: Optional[int] = None

    class Config:
        from_attributes = True


class PlaceInfo(BaseModel):
    place_id: str
    name: Optional[str] = None
    address: Optional[str] = None


class PlaceQASessionListItem(BaseModel):
    session_id: str
    place: Optional[PlaceInfo] = None
    title: str
    last_message: Optional[str] = None  # Preview of last message
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PlaceQASessionDetail(BaseModel):
    session_id: str
    place: Optional[PlaceInfo] = None
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None
    messages: List[PlaceQAMessageSchema] = []

    class Config:
        from_attributes = True

class ListPlaceQASessionsResponse(BaseModel):
    success: bool = True
    sessions: List[PlaceQASessionListItem]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class GetPlaceQASessionResponse(BaseModel):
    success: bool = True
    session: PlaceQASessionDetail
    total_messages: int
    page: int
    page_size: int
    has_next: bool


class DeletePlaceQASessionResponse(BaseModel):
    """Response for deleting a Place Q&A session."""

    success: bool = True
    message: str = "Session deleted successfully"
    deleted_session_ids: List[str]  # Support bulk delete


class UpdateSessionRequest(BaseModel):
    """Request to update session metadata."""
    title: Optional[str] = Field(None, max_length=255)
    archived: Optional[bool] = None


class UpdateSessionResponse(BaseModel):
    """Response after updating session."""
    success: bool = True
    session_id: str
    title: str
