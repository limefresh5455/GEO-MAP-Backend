from datetime import datetime
from typing import List, Optional

from app.schemas.places import NearbySearchResponse, PlaceResult


def build_nearby_response(
    places: List[PlaceResult],
    from_cache: bool,
    search_latitude: float,
    search_longitude: float,
    message: Optional[str] = None,
) -> NearbySearchResponse:
    """Build a standardised NearbySearchResponse envelope."""
    source = "redis_cache" if from_cache else "google_places"
    default_message = (
        "Nearby places returned from cache"
        if from_cache
        else "Nearby places fetched successfully"
    )
    return NearbySearchResponse(
        success=True,
        source=source,
        message=message or default_message,
        data=places,
        total_results=len(places),
        cached=from_cache,
        search_latitude=search_latitude,
        search_longitude=search_longitude,
        timestamp=datetime.utcnow(),
    )
