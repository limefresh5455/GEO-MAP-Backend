import logging
from fastapi import APIRouter, Depends
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.dependencies.auth import get_current_user
from app.dependencies.routes import get_routes_service
from app.exceptions.custom_exceptions import LocationNotFoundError
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
    UserLocationNotFoundError,
)
from app.models.user import User
from app.schemas.routes import (
    ComputeRouteRequest,
    RouteResponse,
)
from app.services.routes_service import RoutesService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["Routes"])

limiter = Limiter(key_func=get_remote_address)


@router.post("/compute", response_model=RouteResponse)
async def compute_route(
    payload: ComputeRouteRequest,
    current_user: User = Depends(get_current_user),
    service: RoutesService = Depends(get_routes_service),
):
    """    
    **Request body:**
    ```json
    {
      "place_id": "ChIJ...",
      "travel_mode": "DRIVE"
    }
    ```
    """
    logger.info(
        "compute_route — user_id: %s, destination: %s, mode: %s",
        current_user.id,
        payload.place_id or f"({payload.destination_latitude}, {payload.destination_longitude})",
        payload.travel_mode.value,
    )

    try:
        response, origin_lat, origin_lon = await service.compute_route(
            request=payload,
            user_id=current_user.id,
        )
    except UserLocationNotFoundError as exc:
        logger.error("compute_route failed — user_id: %s — No location found", current_user.id)
        raise LocationNotFoundError() from exc
    except GooglePlacesRateLimitError:
        logger.warning("compute_route — Routes API rate limit exceeded for user_id: %s", current_user.id)
        raise
    except GooglePlacesTimeoutError:
        logger.error("compute_route — Routes API timed out for user_id: %s", current_user.id)
        raise
    except GooglePlacesAPIError as exc:
        logger.error(
            "compute_route — Routes API error for user_id: %s, destination: %s, error: %s",
            current_user.id,
            payload.place_id,
            str(exc),
        )
        raise
    except Exception as exc:
        logger.critical(
            "compute_route — UNEXPECTED ERROR for user_id: %s, error: %s",
            current_user.id,
            str(exc),
            exc_info=True
        )
        raise

    # Attach origin coordinates to the response metadata for map centering
    response_dict = response.model_dump()
    response_dict["origin_latitude"] = origin_lat
    response_dict["origin_longitude"] = origin_lon
    return response_dict
