"""
Pydantic schemas for the Place Details layer.

Covers:
  GET /api/v1/places/{place_id}/details
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Sub-objects that match Google's nested structures
# ---------------------------------------------------------------------------

class OpeningHoursPeriod(BaseModel):
    """A single open/close period within a day."""
    open_day: Optional[int] = None     # 0=Sunday … 6=Saturday
    open_hour: Optional[int] = None
    open_minute: Optional[int] = None
    close_day: Optional[int] = None
    close_hour: Optional[int] = None
    close_minute: Optional[int] = None


class OpeningHours(BaseModel):
    """Structured opening hours snapshot from Google."""
    open_now: Optional[bool] = None
    weekday_descriptions: Optional[List[str]] = None   # human-readable lines
    periods: Optional[List[OpeningHoursPeriod]] = None


class PlacePhoto(BaseModel):
    """Minimal photo reference — full URL requires a separate Photos API call."""
    name: Optional[str] = None         # resource name: "places/{id}/photos/{ref}"
    width_px: Optional[int] = None
    height_px: Optional[int] = None


class PlaceReview(BaseModel):
    """Single user review as returned by Google."""
    author_name: Optional[str] = None
    rating: Optional[float] = None
    text: Optional[str] = None
    publish_time: Optional[str] = None   # ISO-8601 string from Google
    relative_publish_time_description: Optional[str] = None


# ---------------------------------------------------------------------------
# Full place detail result
# ---------------------------------------------------------------------------

class PlaceDetailResult(BaseModel):
    """
    Normalised full place profile.
    Returned to the frontend on GET /api/v1/places/{place_id}/details.
    Also used as the payload stored in PostgreSQL and cached in Redis.
    """

    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None

    # Coordinates
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Classification
    primary_type: Optional[str] = None
    types: Optional[List[str]] = None

    # Contact
    international_phone_number: Optional[str] = None
    national_phone_number: Optional[str] = None
    website_uri: Optional[str] = None
    google_maps_uri: Optional[str] = None

    # Ratings
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None

    # Status & hours
    business_status: Optional[str] = None
    opening_hours: Optional[OpeningHours] = None
    open_now: Optional[bool] = None            # convenience shortcut

    # Rich data
    photos: Optional[List[PlacePhoto]] = None
    reviews: Optional[List[PlaceReview]] = None

    # Price & accessibility
    price_level: Optional[str] = None
    wheelchair_accessible_entrance: Optional[bool] = None

    # Editorial
    editorial_summary: Optional[str] = None

    # Metadata
    last_fetched_at: Optional[datetime] = None
    knowledge_synced: Optional[bool] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# API response envelope
# ---------------------------------------------------------------------------

class PlaceDetailsResponse(BaseModel):
    """Standard response envelope for GET /api/v1/places/{place_id}/details."""

    success: bool
    source: str                        # "google_places" | "redis_cache" | "database"
    message: str
    data: PlaceDetailResult
    cached: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Internal: data source constants (not exposed to client)
# ---------------------------------------------------------------------------

class DetailSource:
    GOOGLE = "google_places"
    REDIS = "redis_cache"
    DATABASE = "database"
