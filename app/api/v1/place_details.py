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
    place_id: str = Path(..., min_length=1, max_length=255),
    current_user: User = Depends(get_current_user),
    service: PlaceDetailsService = Depends(get_place_details_service),
) -> PlaceDetailsResponse:
    """
    Get full details for a place.
    
    Returns from: Redis cache (instant) → PostgreSQL → Google API
    
    Includes opening hours, reviews, photos, ratings, and contact info.
    Auto-syncs knowledge for Q&A. Cached for 24 hours.
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
