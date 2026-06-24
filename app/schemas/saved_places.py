from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

# ── Save Place ──────────────────────────────────────────────────────────────────


class SavePlaceRequest(BaseModel):
    """Request body for POST /places/{place_id}/save."""

    notes: Optional[str] = Field(None, max_length=500, description="Personal note")
    tags: Optional[List[str]] = Field(
        None, description='e.g. ["want_to_visit", "favorite"]'
    )


class SavedPlaceResponse(BaseModel):
    """Response for a single saved place."""

    id: int
    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    primary_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    saved_location_lat: Optional[float] = Field(
        None, description="User's latitude when they saved this place"
    )
    saved_location_lon: Optional[float] = Field(
        None, description="User's longitude when they saved this place"
    )
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    saved_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Update Saved Place ──────────────────────────────────────────────────────────


class UpdateSavedPlaceRequest(BaseModel):
    """Request body for PATCH /places/saved/{id}."""

    notes: Optional[str] = Field(None, max_length=500)
    tags: Optional[List[str]] = None
    is_archived: Optional[bool] = None


# ── List Saved Places ───────────────────────────────────────────────────────────


class ListSavedPlacesResponse(BaseModel):
    """Response for GET /places/saved."""

    success: bool = True
    data: List[SavedPlaceResponse]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Save/Unsave Actions ─────────────────────────────────────────────────────────


class SavePlaceActionResponse(BaseModel):
    """Generic response for save/unsave actions."""

    success: bool = True
    message: str
    place_id: str
    saved: bool  # True = saved, False = unsaved
    saved_id: Optional[int] = Field(
        None, description="ID of the saved place record (for unsave/update)"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
