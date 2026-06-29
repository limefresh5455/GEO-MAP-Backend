from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator

# Enums


class RankPreference(str, Enum):
    """Google Text Search rankPreference values."""

    RELEVANCE = "RELEVANCE"
    DISTANCE = "DISTANCE"


class NearbyRankPreference(str, Enum):
    """Google Nearby Search rankPreference values."""

    POPULARITY = "POPULARITY"
    DISTANCE = "DISTANCE"


class DiscoveryPreset(str, Enum):

    PREFERRED_TYPES = "preferred_types"
    FAMOUS_PLACES = "famous_places"


class PredefinedPlaceType(str, Enum):

    # Religious places
    TEMPLE = "hindu_temple"  # Hindu temples
    MOSQUE = "mosque"  # Mosques
    CHURCH = "church"  # Churches

    # Food & Dining
    RESTAURANT = "restaurant"  # Restaurants
    CAFE = "cafe"  # Cafes and coffee shops
    BAR = "bar"  # Bars and pubs
    BAKERY = "bakery"  # Bakeries
    MEAL_TAKEAWAY = "meal_takeaway"  # Takeaway food

    # Tourist & Famous Places
    TOURIST_ATTRACTION = "tourist_attraction"  # Famous places, landmarks
    MUSEUM = "museum"  # Museums
    ART_GALLERY = "art_gallery"  # Art galleries
    ZOO = "zoo"  # Zoos
    AQUARIUM = "aquarium"  # Aquariums
    AMUSEMENT_PARK = "amusement_park"  # Amusement parks

    # Nature & Outdoors
    PARK = "park"  # Parks and gardens
    NATIONAL_PARK = "national_park"  # National parks and forests
    CAMPGROUND = "campground"  # Camping areas
    HIKING_AREA = "hiking_area"  # Hiking trails

    # Shopping
    SHOPPING_MALL = "shopping_mall"  # Malls and shopping centers
    STORE = "store"  # Stores
    SUPERMARKET = "supermarket"  # Supermarkets
    CONVENIENCE_STORE = "convenience_store"  # Convenience stores

    # Healthcare
    HOSPITAL = "hospital"  # Hospitals
    DOCTOR = "doctor"  # Doctors
    PHARMACY = "pharmacy"  # Medical stores
    DENTIST = "dentist"  # Dentists

    # Finance
    BANK = "bank"  # Banks
    ATM = "atm"  # ATMs

    # Transportation
    GAS_STATION = "gas_station"  # Petrol pumps
    PARKING = "parking"  # Parking areas
    AIRPORT = "airport"  # Airports
    BUS_STATION = "bus_station"  # Bus stations
    TRAIN_STATION = "train_station"  # Railway stations
    TAXI_STAND = "taxi_stand"  # Taxi stands

    # Accommodation
    HOTEL = "lodging"  # Hotels and lodging

    # Fitness & Recreation
    GYM = "gym"  # Gyms and fitness centers
    SPORTS_COMPLEX = "sports_complex"  # Sports facilities
    STADIUM = "stadium"  # Stadiums

    # Education
    SCHOOL = "school"  # Schools
    UNIVERSITY = "university"  # Universities
    LIBRARY = "library"  # Libraries

    # Entertainment
    MOVIE_THEATER = "movie_theater"  # Cinema halls
    NIGHT_CLUB = "night_club"  # Night clubs
    CASINO = "casino"  # Casinos

    # Emergency Services
    POLICE = "police"  # Police stations
    FIRE_STATION = "fire_station"  # Fire stations

    @classmethod
    def get_all_types(cls) -> List[str]:
        """Return all predefined place type values."""
        return [t.value for t in cls]


# ---------------------------------------------------------------------------
# Shared sub-objects
# ---------------------------------------------------------------------------


class LocationBias(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    radius: float = Field(
        default=5000.0,
        ge=1.0,
        le=50000.0,
        description="Bias radius in metres (1–50 000)",
    )


# ---------------------------------------------------------------------------
# Text Search request
# ---------------------------------------------------------------------------


class TextSearchRequest(BaseModel):
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

    # B-025 FIX: Sanitize text_query to prevent injection attacks
    @field_validator("text_query")
    @classmethod
    def sanitize_text_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text_query must not be empty")

        # Remove null bytes (can cause issues with PostgreSQL)
        v = v.replace("\x00", "")

        # Remove SQL comment markers
        dangerous_patterns = ["--", "/*", "*/", ";--", "';", '";']
        for pattern in dangerous_patterns:
            v = v.replace(pattern, " ")

        # Limit consecutive whitespace
        import re

        v = re.sub(r"\s+", " ", v)

        return v.strip()


# Nearby Search request  (mirrors existing schema, extended for discovery)


class NearbyDiscoveryRequest(BaseModel):
    radius: float = Field(
        default=5000.0,
        ge=100.0,
        le=50000.0,
        description="Search radius in metres (100–50,000). Default: 5km",
    )
    max_result_count: int = Field(
        default=20,
        ge=1,
        le=20,
        description="Maximum places to return (1–20)",
    )
    preset: Optional[DiscoveryPreset] = Field(
        default=None,
        description=(
            "Quick discovery preset:\n"
            "- 'preferred_types': Everyday places (restaurants, cafes, hospitals, shopping, temples)\n"
            "- 'famous_places': Tourist attractions, landmarks, forts, museums, parks\n"
            "If preset is provided, included_types is ignored. "
            "If both preset and included_types are null, defaults to 'preferred_types'."
        ),
    )
    included_types: Optional[List[str]] = Field(
        default=None,
        description=(
            "Custom place type filters, e.g. ['restaurant', 'cafe']. "
            "Ignored if preset is specified. "
            "See Google Places API types or PredefinedPlaceType enum."
        ),
    )
    excluded_types: Optional[List[str]] = Field(
        default=None,
        description="Place types to exclude from results",
    )
    rank_preference: Optional[NearbyRankPreference] = Field(
        default=None,
        description="POPULARITY (default) or DISTANCE",
    )

    @field_validator("included_types", "excluded_types")
    @classmethod
    def validate_types_array(cls, v: Optional[List[str]], info) -> Optional[List[str]]:
        """Ensure types are provided as array, not string."""
        if v is None:
            return v

        # If it's a string, try to parse it
        if isinstance(v, str):
            # Try to parse as comma-separated
            parsed = [t.strip() for t in v.split(",") if t.strip()]
            if parsed:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"{info.field_name} received as string, converted to array: {parsed}"
                )
                return parsed
            return None

        # Ensure it's actually a list
        if not isinstance(v, list):
            raise ValueError(
                f"{info.field_name} must be an array of strings, not {type(v)}"
            )

        # Validate each element is a string
        for item in v:
            if not isinstance(item, str):
                raise ValueError(f"Each type in {info.field_name} must be a string")

        return v


# Discovery Router request


class DiscoverySearchRequest(BaseModel):
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
    # B23 FIX: accept both text and nearby rank preference enums.
    rank_preference: Optional[Union[RankPreference, NearbyRankPreference]] = Field(
        default=None,
        description=(
            "Rank preference hint for the resolved search mode. "
            "RELEVANCE/DISTANCE for text search; POPULARITY/DISTANCE for nearby. "
            "The service passes the .value string to the appropriate Google client."
        ),
    )


# ---------------------------------------------------------------------------
# Shared place result (used in both Text Search and Nearby Search responses)
# ---------------------------------------------------------------------------


class DiscoveryPlaceResult(BaseModel):
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
    open_now: Optional[bool] = None  # from currentOpeningHours if requested

    # Phase 4: New fields for richer search cards
    price_level: Optional[str] = Field(
        default=None,
        description=(
            "Price range indicator from Google. Values: PRICE_LEVEL_FREE, "
            "PRICE_LEVEL_INEXPENSIVE, PRICE_LEVEL_MODERATE, PRICE_LEVEL_EXPENSIVE, "
            "PRICE_LEVEL_VERY_EXPENSIVE. Frontend can map to symbols like $, $$, $$$, $$$$."
        ),
    )
    first_photo_name: Optional[str] = Field(
        default=None,
        description=(
            "Resource name of the first photo for thumbnail preview "
            "(e.g. 'places/ChIJ.../photos/AUac...'). "
            "Call GET /api/v1/places/{place_id}/photos to resolve to CDN URL, "
            "or resolve directly via Places Photos API with this resource name."
        ),
    )


# ---------------------------------------------------------------------------
# Autocomplete (Phase 2)
# ---------------------------------------------------------------------------


class AutocompleteRequest(BaseModel):
    input: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Partial search query (e.g. 'bur' → suggests 'Burj Khalifa')",
    )
    included_primary_types: Optional[List[str]] = Field(
        default=None,
        description="Filter predictions by place types (e.g. ['restaurant', 'cafe'])",
    )
    language_code: str = Field(
        default="en",
        max_length=10,
        description="Preferred language for results (ISO 639-1 code)",
    )
    use_user_location_bias: bool = Field(
        default=True,
        description=(
            "When True, prioritizes predictions near the user's saved location. "
            "If user has no saved location, Google uses IP-based biasing."
        ),
    )


class AutocompletePrediction(BaseModel):
    """A single autocomplete prediction returned by Google."""

    place_id: str = Field(description="Stable Google place ID")
    main_text: str = Field(description="Primary display text (e.g. 'Burj Khalifa')")
    secondary_text: str = Field(
        description="Secondary display text (e.g. 'Dubai, UAE')"
    )
    full_text: str = Field(description="Complete description (main + secondary)")
    types: List[str] = Field(
        description="Place type tags (e.g. ['tourist_attraction'])"
    )


class AutocompleteResponse(BaseModel):
    """Standard envelope for GET /api/v1/discovery/autocomplete."""

    success: bool
    message: str
    input: str  # echoed input for client verification
    predictions: List[AutocompletePrediction]
    total_predictions: int
    cached: bool
    bias_latitude: Optional[float] = None  # user location used as bias (if any)
    bias_longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class TextSearchResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/text-search."""

    success: bool
    search_mode: str  # always "text"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    # B31 FIX: query is Optional — can be None when called from discovery router
    # where query routing may not provide a text query.
    query: Optional[str] = None
    search_latitude: Optional[float] = None  # user location used as bias (if any)
    search_longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NearbyDiscoveryResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/nearby-search."""

    success: bool
    search_mode: str  # always "nearby"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    search_latitude: float
    search_longitude: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiscoverySearchResponse(BaseModel):
    """Standard envelope for POST /api/v1/discovery/search (router)."""

    success: bool
    search_mode: str  # "text" or "nearby"
    message: str
    data: List[DiscoveryPlaceResult]
    total_results: int
    cached: bool
    query: Optional[str] = None
    search_latitude: Optional[float] = None
    search_longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
