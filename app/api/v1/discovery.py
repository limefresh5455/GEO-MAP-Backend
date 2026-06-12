"""
Discovery API — Phase 1 endpoints.

Routes
------
POST /api/v1/discovery/text-search     Free-text Google Text Search (New)
POST /api/v1/discovery/nearby-search   Geo-bounded search (user's saved location)
POST /api/v1/discovery/search          Discovery Router — backend picks the mode

All routes require a valid Bearer token.
All routes follow the same response envelope pattern used by the rest of the API.
"""

import logging

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.discovery import get_discovery_service
from app.models.user import User
from app.schemas.discovery import (
    DiscoveryPlaceResult,
    DiscoverySearchRequest,
    DiscoverySearchResponse,
    NearbyDiscoveryRequest,
    NearbyDiscoveryResponse,
    TextSearchRequest,
    TextSearchResponse,
)
from app.services.discovery_service import DiscoveryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["Discovery"])


# ---------------------------------------------------------------------------
# 1. Text Search
# ---------------------------------------------------------------------------

@router.post("/text-search", response_model=TextSearchResponse)
async def text_search(
    payload: TextSearchRequest,
    current_user: User = Depends(get_current_user),
    service: DiscoveryService = Depends(get_discovery_service),
) -> TextSearchResponse:
    """
    Search for places using a natural-language text query.

    Examples of valid queries:
    - "best coffee near me"
    - "budget hospitals in Raipur"
    - "pizza places open now"
    - "bookstores near Connaught Place"

    **How it works:**
    1. If `use_user_location_as_bias` is `true` (default), the backend automatically
       injects the authenticated user's saved location as a soft location bias.
    2. An explicit `location_bias` in the payload overrides the auto-injected one.
    3. If no location is available, Google uses IP-based biasing.
    4. Results are cached in Redis for 60 minutes and audited in PostgreSQL.

    **Note:** `locationBias` and `locationRestriction` are mutually exclusive in
    Google's API. This endpoint uses `locationBias` only (soft preference).
    Use `/discovery/nearby-search` for hard location restriction.
    """
    logger.info(
        "Text Search — user_id: %s, query: %r, max: %s",
        current_user.id,
        payload.text_query,
        payload.max_result_count,
    )

    places, from_cache, lat, lon = await service.text_search(
        request=payload,
        user_id=current_user.id,
    )

    source_msg = "from cache" if from_cache else "from Google"
    return TextSearchResponse(
        success=True,
        search_mode="text",
        message=f"Text search completed ({source_msg})",
        data=places,
        total_results=len(places),
        cached=from_cache,
        query=payload.text_query,
        search_latitude=lat,
        search_longitude=lon,
    )


# ---------------------------------------------------------------------------
# 2. Nearby Search (Discovery path — uses user's saved location)
# ---------------------------------------------------------------------------

@router.post("/nearby-search", response_model=NearbyDiscoveryResponse)
async def nearby_search(
    payload: NearbyDiscoveryRequest,
    current_user: User = Depends(get_current_user),
    service: DiscoveryService = Depends(get_discovery_service),
) -> NearbyDiscoveryResponse:
    """
    Search for places within a geo-bounded radius around the user's saved location.

    **How it works:**
    1. The backend reads the authenticated user's active current location from PostgreSQL.
    2. That coordinate pair becomes the centre of a `locationRestriction` circle.
    3. Results are cached in Redis for 60 minutes and audited in PostgreSQL.

    **Requires:** User must have called `POST /api/v1/locations/gps` or
    `PUT /api/v1/locations/manual` at least once.  Returns HTTP 404 if no
    saved location is found.

    **Type filters:** Pass `included_types` or `excluded_types` to narrow
    results to specific Google place categories (e.g. `["restaurant"]`).
    """
    logger.info(
        "Nearby Discovery — user_id: %s, radius: %sm, max: %s",
        current_user.id,
        payload.radius,
        payload.max_result_count,
    )

    places, from_cache, lat, lon = await service.nearby_search(
        request=payload,
        user_id=current_user.id,
    )

    source_msg = "from cache" if from_cache else "from Google"
    return NearbyDiscoveryResponse(
        success=True,
        search_mode="nearby",
        message=f"Nearby search completed ({source_msg})",
        data=places,
        total_results=len(places),
        cached=from_cache,
        search_latitude=lat,
        search_longitude=lon,
    )


# ---------------------------------------------------------------------------
# 3. Discovery Router — single entry point for the React frontend
# ---------------------------------------------------------------------------

@router.post("/search", response_model=DiscoverySearchResponse)
async def discovery_search(
    payload: DiscoverySearchRequest,
    current_user: User = Depends(get_current_user),
    service: DiscoveryService = Depends(get_discovery_service),
) -> DiscoverySearchResponse:
    """
    Unified discovery endpoint — the backend automatically decides whether
    to run a Text Search or a Nearby Search based on the user's query.

    **Routing logic (applied in order):**
    1. No `query` provided → **Nearby Search** (pure location browse).
    2. Query contains geo-signal words ("near me", "around me", "nearest", etc.)
       → **Nearby Search** with the user's saved location.
    3. All other text queries → **Text Search** with user's location as soft bias.

    **Why use this instead of calling text-search or nearby-search directly?**
    The frontend sends one payload with whatever the user typed.  The backend
    owns the routing decision, keeping the frontend simple and the search
    strategy consistent.

    Returns the same place list regardless of which mode ran, plus a
    `search_mode` field so the UI can show the right label.
    """
    logger.info(
        "Discovery Router — user_id: %s, query: %r",
        current_user.id,
        payload.query,
    )

    places, from_cache, resolved_mode, lat, lon = await service.discovery_search(
        request=payload,
        user_id=current_user.id,
    )

    source_msg = "from cache" if from_cache else "from Google"
    mode_label = "Text Search" if resolved_mode == "text" else "Nearby Search"
    return DiscoverySearchResponse(
        success=True,
        search_mode=resolved_mode,
        message=f"{mode_label} completed ({source_msg})",
        data=places,
        total_results=len(places),
        cached=from_cache,
        query=payload.query,
        search_latitude=lat,
        search_longitude=lon,
    )
