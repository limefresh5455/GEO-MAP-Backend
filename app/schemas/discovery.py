"""
Pydantic schemas for the Discovery layer.

Covers three endpoints:
  POST /api/v1/discovery/text-search     — free-text search
  POST /api/v1/discovery/nearby-search   — location-bounded search
  POST /api/v1/discovery/search          — router (auto-picks mode)
"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RankPreference(str, Enum):
    """Google Text Search rankPreference values."""
    RELEVANCE = "RELEVANCE"
    DISTANCE = "DISTANCE"


class NearbyRankPreference(str, Enum):
    """Google Nearby Search rankPreference values."""
    POPULARITY = "POPULARITY"
    DISTANCE = "DISTANCE"


# ---------------------------------------------------------------------------
# Shared sub-objects
# ---------------------------------------------------------------------------

class LocationBias(BaseModel):
    """
    Optional location hint for text search.
    Acts as a soft preference — results outside the area can still appear.
    """
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    radius: float = Field(default=5000.0, ge=1.0, le=50000.0,
                          description="Bias radius in metres (1–50 000)")


# ---------------------------------------------------------------------------
# Text Search request
# ---------------------------------------------------------------------------

class TextSearchRequest(BaseModel):
    """
    Payload for POST /api/v1/discovery/text-search.

    text_query is the only required field.
    All other fields are optional refinements passed to Google.
    """

    text_query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural-language search query, e.g. 'best coffee near me'",
    )
    location_bias: Optional[LocationBias] = Field(
        default=None,
        description=(
            "Soft location preference. If omitted, use authenticated user's "
            "saved location when available, otherwise Google uses IP biasing."
        ),
    )
    # Optional Google refinement fields
    open_now: Optional[bool] = Field(
        default=None,
        description="Filter to only currently open places",
    )
    min_rating: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Minimum Google rating (0.0–5.0)",
    )
    max_result_count: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Maximum places to return (1–20, Google hard limit)",
    )
    rank_preference: Optional[RankPreference] = Field(
        default=None,
        description="RELEVANCE (default) or DISTANCE",
    )
    use_user_location_as_bias: bool = Field(
        default=True,
        description=(
            "When True, the backend automatically injects the authenticated "
            "user's current saved location as locationBias if no explicit "
            "location_bias is provided."
        ),
    )


# ---------------------------------------------------------------------------
# Nearby Search request  (mirrors existing schema, extended for discovery)
# ---------------------------------------------------------------------------

class NearbyDiscoveryRequest(BaseModel):
    """
    Payload for POST /api/v1/discovery/nearby-search.
    Coordinates are resolved server-side from the user's saved location.
    """

    radius: float = Field(
        default=500.0,
        ge=1.0,
        le=50000.0,
        description="Search radius in metres (1–50 000)",
    )
    max_result_count: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Maximum places to return (1–20)",
    )
    included_types: Optional[List[str]] = Field(
        default=None,
        description="Google place type filters, e.g. ['restaurant', 'cafe']",
    )
    excluded_types: Optional[List[str]] = Field(
        default=None,
        description="Place types to exclude from results",
    )
    rank_preference: Optional[NearbyRankPreference] = Field(
        default=None,
        description="POPULARITY (default) or DISTANCE",
    )


# ---------------------------------------------------------------------------
# Discovery Router request
# ---------------------------------------------------------------------------

class DiscoverySearchRequest(BaseModel):
    """
    Payload for POST /api/v1/discovery/search.

    The backend inspects query and other fields to decide whether to
    call Text Search or Nearby Search — the frontend does not need to know.
    """

    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "Free-text user query. If absent, falls back to nearby search "
            "using the user's saved location."
        ),
    )
    radius: float = Field(
        default=500.0,
        ge=1.0,
        le=50000.0,
        description="Search radius in metres — used by nearby mode",
    )
    max_result_count: int = Field(
        default=20,
        ge=1,
        le=20,
    )
    open_now: Optional[bool] = Field(default=None)
    min_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    rank_preference: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Shared place result (used in both Text Search and Nearby Search responses)
# ---------------------------------------------------------------------------

class DiscoveryPlaceResult(BaseModel):
    """Normalised single place as returned to the frontend from any search mode."""

    place_id: Optional[str] = None
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    primary_type: Optional[str] = None
    types: Optional[List[str]] = None
    business_status: Optional[str] = None
    google_maps_uri: Optional[str] = None
    open_now: Optional[bool] = None            # from currentOpeningHours if requested


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class TextSearchResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/text-search."""

    success: bool
    search_mode: str                           # always "text"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    query: str
    search_latitude: Optional[float] = None   # user location used as bias (if any)
    search_longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class NearbyDiscoveryResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/nearby-search."""

    success: bool
    search_mode: str                           # always "nearby"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    search_latitude: float
    search_longitude: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DiscoverySearchResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/search (router)."""

    success: bool
    search_mode: str                           # "text" or "nearby"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    query: Optional[str] = None
    search_latitude: Optional[float] = None
    search_longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
