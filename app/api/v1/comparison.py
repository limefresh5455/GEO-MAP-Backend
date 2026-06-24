import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.comparison import (
    ComparePlacesRequest,
    ComparePlacesResponse,
)
from app.services.comparison_service import ComparisonService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compare", tags=["Comparison"])


def _get_comparison_service(db: Session = Depends(get_db)) -> ComparisonService:
    return ComparisonService(db)


@router.post("", response_model=ComparePlacesResponse)
async def compare_places(
    body: ComparePlacesRequest,
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(_get_comparison_service),
):
    """Compare 2-10 places side-by-side across all attributes.

    Shows ratings, price levels, amenities, accessibility, opening hours,
    dining options, parking, payment methods, and more.

    **Note:** Places must have their details fetched first via GET /places/{id}/details.
    """
    result = await service.compare(
        place_ids=body.place_ids,
        fields=body.fields,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result


@router.get("/batch", response_model=ComparePlacesResponse)
async def compare_places_get(
    ids: str = Query(
        ...,
        description="Comma-separated list of 2-10 place IDs",
        min_length=1,
    ),
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(_get_comparison_service),
):
    """Compare places via GET with comma-separated place IDs.

    Example: `/compare/batch?ids=ChIJabc,ChIJdef,ChIJghi`
    """
    pids = [pid.strip() for pid in ids.split(",") if pid.strip()]
    if len(pids) < 2 or len(pids) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide between 2 and 10 comma-separated place IDs.",
        )
    result = await service.compare(place_ids=pids)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result
