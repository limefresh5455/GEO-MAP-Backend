from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class TravelMode(str, Enum):
    DRIVE = "DRIVE"
    WALK = "WALK"
    BICYCLE = "BICYCLE"
    TWO_WHEELER = "TWO_WHEELER"


class RoutingPreference(str, Enum):
    TRAFFIC_AWARE = "TRAFFIC_AWARE"
    TRAFFIC_AWARE_OPTIMAL = "TRAFFIC_AWARE_OPTIMAL"   # more compute, more accurate
    TRAFFIC_UNAWARE = "TRAFFIC_UNAWARE"               # required for WALK / BICYCLE


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ComputeRouteRequest(BaseModel):
    # Destination — prefer place_id, fall back to raw coordinates
    place_id: Optional[str] = Field(
        default=None,
        description=(
            "Google place_id of the destination. Preferred over raw coordinates "
            "because Google resolves it internally without a geocoding step."
        ),
    )
    destination_latitude: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Fallback: destination latitude when place_id is not available",
    )
    destination_longitude: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Fallback: destination longitude when place_id is not available",
    )

    # Multi-stop support (Phase 6)
    waypoints: List[Dict[str, Any]] = Field(
        default=[],
        max_length=25,
        description=(
            "Intermediate stops between origin and destination. "
            "Each waypoint should have 'place_id' or 'lat'+'lon'. "
            "Maximum 25 waypoints."
        ),
    )
    optimize_waypoint_order: bool = Field(
        default=False,
        description=(
            "When True, Google optimizes waypoint order to minimize travel time. "
            "Useful for delivery routes or multi-destination trips."
        ),
    )

    # Departure time support (Phase 7)
    departure_time: Optional[datetime] = Field(
        default=None,
        description=(
            "ISO 8601 datetime for when the user plans to depart. "
            "When provided, Google calculates predicted traffic conditions "
            "for that time. Must be in the future."
        ),
    )

    # Route options
    travel_mode: TravelMode = Field(
        default=TravelMode.DRIVE,
        description="DRIVE (default) or WALK",
    )
    language_code: str = Field(
        default="en-US",
        max_length=10,
        description="BCP-47 language tag for navigation instruction text",
    )
    avoid_tolls: bool = Field(default=False)
    avoid_highways: bool = Field(default=False)
    avoid_ferries: bool = Field(default=False)

    def has_valid_destination(self) -> bool:
        """Returns True if destination is fully specified via coordinates."""
        return (
            self.destination_latitude is not None
            and self.destination_longitude is not None
        )


class ComputeRouteMatrixRequest(BaseModel):
    # List of destinations from discovery results
    destinations: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=20,  # caps at discovery max_result_count
        description=(
            "List of destination objects. Each must have at least "
            "'lat' and 'lon' keys. 'place_id' is optional but preferred."
        ),
    )
    travel_mode: TravelMode = Field(default=TravelMode.DRIVE)


class NavigationStep(BaseModel):
    """A single turn-by-turn navigation step."""
    distance_meters: int = 0
    duration_seconds: int = 0
    maneuver: Optional[str] = None          # e.g. "TURN_LEFT", "STRAIGHT"
    instruction: Optional[str] = None       # human-readable, e.g. "Turn left onto Main St"


class RouteResult(BaseModel):
    distance_meters: int
    duration_seconds: int
    static_duration_seconds: int           # without live traffic
    traffic_delay_seconds: int = 0         # duration - static_duration
    distance_text: Optional[str] = None    # "1.2 km"
    duration_text: Optional[str] = None    # "12 min"
    traffic_delay_text: Optional[str] = None  # "4 min delay"
    encoded_polyline: str                  # Google's encoded polyline format
    steps: List[NavigationStep] = []
    optimized_waypoint_order: Optional[List[int]] = None  # Phase 6: reordered indices


class RouteMatrixElement(BaseModel):
    origin_index: int
    destination_index: int
    distance_meters: Optional[int] = None   # None when destination is unreachable
    duration_seconds: Optional[int] = None  # None when destination is unreachable
    condition: str = "ROUTE_EXISTS"         # "ROUTE_EXISTS" | "ROUTE_NOT_FOUND" | etc.

class RouteResponse(BaseModel):
    success: bool
    message: str
    cached: bool = False
    travel_mode: str
    data: Optional[RouteResult] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RouteMatrixItem(BaseModel):
    destination_index: int
    place_id: Optional[str] = None
    distance_meters: Optional[int] = None
    duration_seconds: Optional[int] = None
    distance_text: Optional[str] = None    # human-readable, e.g. "1.2 km"
    duration_text: Optional[str] = None    # human-readable, e.g. "8 min"
    reachable: bool = True


class RouteMatrixResponse(BaseModel):
    success: bool
    message: str
    cached: bool = False
    travel_mode: str
    origin_latitude: float
    origin_longitude: float
    data: List[RouteMatrixItem]
    total_destinations: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
