from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class NearbySearchRequest(BaseModel):
    """
    Client payload for nearby places search.

    latitude and longitude are intentionally excluded.
    The backend resolves coordinates from the authenticated user's
    saved location in the database.
    """

    radius: float = Field(
        default=500.0,
        ge=1.0,
        le=5000.0,
        description="Search radius in metres (1–5000)",
    )
    max_result_count: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Maximum number of places to return (1–20)",
    )


# ---------------------------------------------------------------------------
# Place result
# ---------------------------------------------------------------------------

class PlaceResult(BaseModel):
    """Normalised single place from Google Places API."""

    place_id: Optional[str] = None
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    primary_type: Optional[str] = None
    business_status: Optional[str] = None
    google_maps_uri: Optional[str] = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class NearbySearchResponse(BaseModel):
    """Standard response envelope for nearby search."""

    success: bool
    source: str                        # "google_places" | "redis_cache"
    message: str
    data: List[PlaceResult]
    total_results: int
    cached: bool
    search_latitude: float             # coordinates actually used for this search
    search_longitude: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
