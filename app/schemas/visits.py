from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

# ── Log Visit ───────────────────────────────────────────────────────────────────


class LogVisitRequest(BaseModel):
    """Request body for POST /places/{place_id}/visit."""

    rating_given: Optional[float] = Field(
        None, ge=1, le=5, description="Personal rating 1-5 (accepts whole numbers or decimals)"
    )
    review_text: Optional[str] = Field(None, max_length=2000)
    with_whom: Optional[str] = Field(
        None, max_length=100, description="e.g. family, friends, solo, partner"
    )
    mood: Optional[str] = Field(
        None, max_length=50, description="e.g. romantic, fun, quiet"
    )


class VisitLogResponse(BaseModel):
    """Response for a single visit log entry."""

    id: int
    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating_given: Optional[float] = None
    review_text: Optional[str] = None
    with_whom: Optional[str] = None
    mood: Optional[str] = None
    visited_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Update Visit ────────────────────────────────────────────────────────────────


class UpdateVisitRequest(BaseModel):
    """Request body for PATCH /visits/{id}."""

    rating_given: Optional[float] = Field(None, ge=1, le=5)
    review_text: Optional[str] = Field(None, max_length=2000)
    with_whom: Optional[str] = Field(None, max_length=100)
    mood: Optional[str] = Field(None, max_length=50)


# ── List Visits ─────────────────────────────────────────────────────────────────


class ListVisitsResponse(BaseModel):
    """Response for GET /visits."""

    success: bool = True
    data: List[VisitLogResponse]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Visit Stats ─────────────────────────────────────────────────────────────────


class VisitStatsResponse(BaseModel):
    """Response for GET /visits/stats."""

    success: bool = True
    total_visits: int
    unique_places: int
    by_category: dict = Field(default_factory=dict)
    by_month: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Log Visit Response ──────────────────────────────────────────────────────────


class LogVisitActionResponse(BaseModel):
    """Response for POST /places/{place_id}/visit."""

    success: bool = True
    message: str
    place_id: str
    visit_id: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeleteVisitResponse(BaseModel):
    """Response for DELETE /visits/{id}."""

    success: bool = True
    message: str
    visit_id: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
