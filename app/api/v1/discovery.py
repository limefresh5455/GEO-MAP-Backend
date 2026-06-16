import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import get_current_user
from app.dependencies.discovery import get_discovery_service
from app.models.user import User
from app.schemas.discovery import (
    AutocompleteRequest,
    AutocompleteResponse,
    AutocompletePrediction,
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

@router.post("/text-search", response_model=TextSearchResponse)
async def text_search(
    payload: TextSearchRequest,
    current_user: User = Depends(get_current_user),
    service: DiscoveryService = Depends(get_discovery_service),
) -> TextSearchResponse:
    """
    Search places using natural-language text query.
    
    **Request body:**
    ```json
    {
      "text_query": "best coffee near me",
      "max_result_count": 20,
      "use_user_location_as_bias": true
    }
    ```
    
    Results cached for 60 minutes.
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
    Search places within radius around user's saved location.
    
    **Request body - Predefined types:**
    ```json
    {
      "radius": 5000,
      "max_result_count": 20,
      "use_predefined_types": true
    }
    ```
    
    **Request body - Custom types:**
    ```json
    {
      "radius": 3000,
      "max_result_count": 15,
      "included_types": ["restaurant", "cafe"]
    }
    ```
    
    User must save location first. Results cached for 60 minutes.
    """
    
    logger.info(
        "Nearby Discovery — user_id: %s, radius: %sm, max: %s, predefined: %s",
        current_user.id,
        payload.radius,
        payload.max_result_count,
        payload.use_predefined_types,
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
    Unified discovery - backend auto-selects text or nearby search based on query.
    
    **Request body:**
    ```json
    {
      "query": "restaurants near me",
      "radius": 5000,
      "max_result_count": 20
    }
    ```
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


# ---------------------------------------------------------------------------
# 4. Autocomplete (Phase 2 — Search UX)
# ---------------------------------------------------------------------------

@router.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    input: str = Query(..., min_length=1, max_length=200),
    included_primary_types: Optional[str] = Query(default=None),
    language_code: str = Query(default="en", max_length=10),
    use_user_location_bias: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    service: DiscoveryService = Depends(get_discovery_service),
) -> AutocompleteResponse:
    """
    Get place autocomplete predictions as user types.
    
    **Example:** `?input=coffee&included_primary_types=restaurant,cafe`
    
    Results cached for 5 minutes.
    """
    logger.info(
        "Autocomplete request — user_id: %s, input: %r",
        current_user.id,
        input,
    )

    # Parse comma-separated types into a list
    types_list = None
    if included_primary_types:
        types_list = [t.strip() for t in included_primary_types.split(",") if t.strip()]

    predictions_raw, from_cache, bias_lat, bias_lon = await service.autocomplete(
        input_text=input,
        user_id=current_user.id,
        included_primary_types=types_list,
        language_code=language_code,
        use_user_location_bias=use_user_location_bias,
    )

    # Convert raw dicts to Pydantic models
    predictions = [AutocompletePrediction(**p) for p in predictions_raw]

    source_msg = "from cache" if from_cache else "from Google"
    return AutocompleteResponse(
        success=True,
        message=f"Autocomplete completed ({source_msg})",
        input=input,
        predictions=predictions,
        total_predictions=len(predictions),
        cached=from_cache,
        bias_latitude=bias_lat,
        bias_longitude=bias_lon,
    )
