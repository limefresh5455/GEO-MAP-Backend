"""
Place Details API — Phase 2.

Routes
------
GET /api/v1/places/{place_id}/details
    Full place profile fetched via Redis → PostgreSQL → Google priority chain.

All routes require a valid Bearer token.
The place_id in the path is the Google place ID returned by any search endpoint.
"""

import logging

from fastapi import APIRouter, Depends, Path

from app.dependencies.auth import get_current_user
from app.dependencies.place_details import get_place_details_service
from app.models.user import User
from app.schemas.place_details import PlaceDetailsResponse
from app.services.place_details_service import PlaceDetailsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["Place Details"])


@router.get("/{place_id}/details", response_model=PlaceDetailsResponse)
async def get_place_details(
    place_id: str = Path(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Google place ID returned by any discovery search endpoint "
            "(e.g. 'ChIJ...'). Do NOT include the 'places/' resource prefix."
        ),
    ),
    current_user: User = Depends(get_current_user),
    service: PlaceDetailsService = Depends(get_place_details_service),
) -> PlaceDetailsResponse:
    """
    Retrieve the full detail profile for a specific place.

    **Lookup priority:**
    1. **Redis cache** — returned immediately if present (TTL: 24 hours).
    2. **PostgreSQL** — returned from the local DB if previously fetched;
       Redis cache is refreshed on every DB hit.
    3. **Google Place Details (New)** — called only on a full miss;
       result is persisted to PostgreSQL and cached in Redis.

    **What's included:**
    - Display name, address, coordinates
    - Opening hours with weekday descriptions
    - Phone numbers, website, Google Maps link
    - Rating, review count, price level
    - Up to 5 photos (resource names — full URLs require the Photos API)
    - Up to 5 recent reviews
    - Business status and accessibility flags
    - Editorial summary (where available)

    **After clicking a search result:**
    Pass the `place_id` from any `/discovery/*` response directly to this endpoint.

    **Required:** `Authorization: Bearer <token>`
    """
    logger.info(
        "Place Details request — user_id: %s, place_id: %s",
        current_user.id,
        place_id,
    )

    detail, source = await service.get_place_details(place_id)

    source_messages = {
        "redis_cache": "Place details returned from cache",
        "database": "Place details returned from local database",
        "google_places": "Place details fetched from Google",
    }

    return PlaceDetailsResponse(
        success=True,
        source=source,
        message=source_messages.get(source, "Place details retrieved"),
        data=detail,
        cached=(source == "redis_cache"),
    )
