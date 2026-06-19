import logging

from fastapi import APIRouter, Depends, Path, Query

from app.dependencies.auth import get_current_user
from app.dependencies.place_photos import get_place_photos_service
from app.exceptions.places import PlaceDetailNotFoundError
from app.models.user import User
from app.schemas.place_photos import PlacePhotosResponse
from app.services.place_photos_service import PlacePhotosService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["Place Photos"])


@router.get("/{place_id}/photos", response_model=PlacePhotosResponse)
async def get_place_photos(
    place_id: str = Path(..., min_length=1, max_length=255),
    max_photos: int = Query(default=5, ge=1, le=10),
    max_width_px: int = Query(default=800, ge=100, le=4800),
    current_user: User = Depends(get_current_user),
    service: PlacePhotosService = Depends(get_place_photos_service),
) -> PlacePhotosResponse:
    logger.info(
        "Place Photos request — user_id: %s, place_id: %s, "
        "max_photos: %d, max_width_px: %d",
        current_user.id,
        place_id,
        max_photos,
        max_width_px,
    )

    return await service.get_place_photos(
        place_id=place_id,
        max_photos=max_photos,
        max_width_px=max_width_px,
    )
