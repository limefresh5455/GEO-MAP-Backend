from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ── Comparison Request ────────────────────────────────────────────────────


class ComparePlacesRequest(BaseModel):
    place_ids: List[str] = Field(..., min_length=2, max_length=10)
    fields: Optional[List[str]] = Field(
        None,
        description="Subset of attributes to compare. If omitted, compares all.",
    )


# ── Comparison Data ───────────────────────────────────────────────────────


class ComparedAttribute(BaseModel):
    """A single attribute (e.g. 'rating') with values for each place."""

    key: str
    label: str
    values: List[Dict[str, Any]]
    """Array of {place_id, value} pairs for this attribute."""


class ComparisonResult(BaseModel):
    """Comparison result for a single place."""

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

    # Extended amenities (from Google Places extended_data)
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

    # Wikipedia / OSM enrichment
    wikipedia_extract: Optional[str] = None
    neighborhood: Optional[str] = None

    model_config = {"from_attributes": True}


class ComparePlacesResponse(BaseModel):
    success: bool = True
    message: str
    comparison: List[ComparisonResult]
    """All places side-by-side with their attribute values."""
    highlights: Optional[Dict[str, Any]] = Field(
        None,
        description="Best-in-class values per attribute",
    )
    total_places: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
