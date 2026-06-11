import logging

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.places import get_places_service
from app.models.user import User
from app.schemas.places import NearbySearchRequest, NearbySearchResponse
from app.services.places_service import PlacesService
from app.utils.response import build_nearby_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["Places"])


@router.post("/nearby-search", response_model=NearbySearchResponse)
async def nearby_search(
    payload: NearbySearchRequest,
    current_user: User = Depends(get_current_user),
    service: PlacesService = Depends(get_places_service),
):
    """
    Search for all nearby places around the authenticated user's saved location.

    The frontend does NOT send coordinates.
    The backend reads the user's latest saved location from PostgreSQL.

    Priority:
      1. Latest active location (is_current=True, is_active=True)
         — regardless of whether it was set via GPS or manual update
      2. No location → HTTP 404 with instructions to update location first

    Cache strategy:
      - Redis cache-aside pattern
      - TTL: 60 minutes
      - Key: nearby:{user_id}:{lat}:{lon}:{radius}:{max_result_count}
      - Location change → new cache entry automatically

    Returns all place types — no category restriction.
    Requires: Authorization: Bearer <token>
    """
    logger.info(
        "Nearby search request — user_id: %s, radius: %sm, max: %s",
        current_user.id,
        payload.radius,
        payload.max_result_count,
    )

    places, from_cache, search_lat, search_lon = await service.search_nearby(
        request=payload,
        user_id=current_user.id,
    )

    return build_nearby_response(
        places=places,
        from_cache=from_cache,
        search_latitude=search_lat,
        search_longitude=search_lon,
    )
