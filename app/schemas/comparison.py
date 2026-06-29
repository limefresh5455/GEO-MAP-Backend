from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Comparison Request


class ComparePlacesRequest(BaseModel):
    place_ids: List[str] = Field(..., min_length=2, max_length=10)


# User Personal Context (saved + visit data)


class PlaceUserContext(BaseModel):
    """The user's personal relationship with a place — saved & visit status."""

    is_saved: bool = False
    saved_id: Optional[int] = None
    saved_at: Optional[datetime] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

    has_visited: bool = False
    visited_at: Optional[datetime] = None
    your_rating: Optional[float] = None
    your_review: Optional[str] = None
    visit_mood: Optional[str] = None
    visited_with: Optional[str] = None


# Side-by-Side Attribute Column


class AttributeValue(BaseModel):
    """Value for a single place within an attribute column."""

    place_id: str
    value: Any = None
    label: Optional[str] = None


class AttributeColumn(BaseModel):

    key: str
    label: str
    values: List[AttributeValue]


# Enhanced Comparison Result (Basic API)


class ReviewSummary(BaseModel):
    """A single Google review snippet."""

    author_name: Optional[str] = None
    rating: Optional[float] = None
    text: Optional[str] = None
    relative_time: Optional[str] = None


class PhotoReference(BaseModel):
    """A single photo reference."""

    name: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None


class EnhancedComparisonResult(BaseModel):
    """Full place data for comparison — all attributes + user context + media."""

    # Core identity
    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    primary_type: Optional[str] = None
    types: Optional[List[str]] = None

    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_from_you_km: Optional[float] = None

    # Ratings & popularity
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    price_level: Optional[str] = None

    # Status
    business_status: Optional[str] = None
    open_now: Optional[bool] = None
    opening_hours_summary: Optional[str] = None

    # Accessibility
    wheelchair_accessible: Optional[bool] = None

    # Contact
    website_uri: Optional[str] = None
    phone_number: Optional[str] = None
    google_maps_uri: Optional[str] = None

    # Editorial
    editorial_summary: Optional[str] = None

    # Media (NEW — richer)
    photo_references: Optional[List[PhotoReference]] = None
    top_reviews: Optional[List[ReviewSummary]] = None

    # Extended amenities
    dine_in: Optional[bool] = None
    takeout: Optional[bool] = None
    delivery: Optional[bool] = None
    curbside_pickup: Optional[bool] = None
    serves_breakfast: Optional[bool] = None
    serves_lunch: Optional[bool] = None
    serves_dinner: Optional[bool] = None
    serves_brunch: Optional[bool] = None
    serves_beer: Optional[bool] = None
    serves_wine: Optional[bool] = None
    serves_cocktails: Optional[bool] = None
    serves_vegetarian_food: Optional[bool] = None
    outdoor_seating: Optional[bool] = None
    restroom: Optional[bool] = None
    good_for_children: Optional[bool] = None
    good_for_groups: Optional[bool] = None
    live_music: Optional[bool] = None
    reservable: Optional[bool] = None
    allows_dogs: Optional[bool] = None
    parking_free: Optional[bool] = None
    parking_paid: Optional[bool] = None
    parking_valet: Optional[bool] = None
    ev_charging: Optional[bool] = None
    payment_cash: Optional[bool] = None
    payment_credit_cards: Optional[bool] = None
    payment_contactless: Optional[bool] = None
    payment_nfc: Optional[bool] = None

    # Wikipedia / OSM enrichment
    wikipedia_extract: Optional[str] = None
    neighborhood: Optional[str] = None

    # User's personal context (NEW)
    your_context: Optional[PlaceUserContext] = None

    model_config = {"from_attributes": True}


# ── Basic Comparison Response ─────────────────────────────────────────────


class CompareBasicResponse(BaseModel):
    """Side-by-side comparison with attribute table + user context."""

    success: bool = True
    message: str
    places: List[EnhancedComparisonResult]
    attribute_table: List[AttributeColumn]
    highlights: Optional[Dict[str, Any]] = Field(
        None,
        description="Best-in-class values per attribute",
    )
    total_places: int
    user_location_used: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Recommendation Score & Result ─────────────────────────────────────────


class ScoreBreakdown(BaseModel):
    """Detailed breakdown of how the recommendation score was computed."""

    rating: float = 0.0
    popularity: float = 0.0
    price_fit: float = 0.0
    amenities: float = 0.0
    proximity: float = 0.0
    user_affinity: float = 0.0


class RecommendationResult(BaseModel):
    """A single recommended place with score and explanation."""

    rank: int
    place_id: str
    display_name: Optional[str] = None
    primary_type: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    price_level: Optional[str] = None
    photo_references: Optional[List[PhotoReference]] = None
    overall_score: float
    score_breakdown: ScoreBreakdown
    strengths: List[str] = []
    your_context: Optional[PlaceUserContext] = None
    ai_summary: Optional[str] = None


# ── Recommendation Response ───────────────────────────────────────────────


class CompareRecommendResponse(BaseModel):
    """Ranked recommendation with AI-powered summary."""

    success: bool = True
    message: str
    recommendations: List[RecommendationResult]
    overall_ai_summary: Optional[str] = None
    total_places_compared: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Legacy Schemas (kept for backward compatibility if needed) ────────────


class ComparisonResult(BaseModel):
    """Legacy comparison result — kept for backward compat."""

    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    primary_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    price_level: Optional[str] = None
    business_status: Optional[str] = None
    open_now: Optional[bool] = None
    opening_hours_summary: Optional[str] = None
    wheelchair_accessible: Optional[bool] = None
    website_uri: Optional[str] = None
    phone_number: Optional[str] = None
    editorial_summary: Optional[str] = None
    photo_name: Optional[str] = None

    dine_in: Optional[bool] = None
    takeout: Optional[bool] = None
    delivery: Optional[bool] = None
    curbside_pickup: Optional[bool] = None
    serves_breakfast: Optional[bool] = None
    serves_lunch: Optional[bool] = None
    serves_dinner: Optional[bool] = None
    serves_brunch: Optional[bool] = None
    serves_beer: Optional[bool] = None
    serves_wine: Optional[bool] = None
    serves_cocktails: Optional[bool] = None
    serves_vegetarian_food: Optional[bool] = None
    outdoor_seating: Optional[bool] = None
    restroom: Optional[bool] = None
    good_for_children: Optional[bool] = None
    good_for_groups: Optional[bool] = None
    live_music: Optional[bool] = None
    reservable: Optional[bool] = None
    parking_free: Optional[bool] = None
    parking_paid: Optional[bool] = None
    parking_valet: Optional[bool] = None
    ev_charging: Optional[bool] = None
    payment_cash: Optional[bool] = None
    payment_credit_cards: Optional[bool] = None
    payment_contactless: Optional[bool] = None
    payment_nfc: Optional[bool] = None

    wikipedia_extract: Optional[str] = None
    neighborhood: Optional[str] = None

    model_config = {"from_attributes": True}


class ComparePlacesResponse(BaseModel):
    success: bool = True
    message: str
    comparison: List[ComparisonResult]
    highlights: Optional[Dict[str, Any]] = None
    total_places: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
