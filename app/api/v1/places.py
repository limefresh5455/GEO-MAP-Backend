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
    Search all nearby places around user's saved location.
    
    **Request body:**
    ```json
    {
      "radius": 5000,
      "max_result_count": 20
    }
    ```
    
    Returns all place types. Cached for 60 minutes.
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
