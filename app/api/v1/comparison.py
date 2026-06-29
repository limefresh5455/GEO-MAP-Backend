import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.rate_limiter import shared_limiter as limiter
from app.dependencies.auth import get_current_user
from app.dependencies.comparison import get_comparison_service
from app.models.user import User
from app.schemas.comparison import (
    CompareBasicResponse,
    ComparePlacesRequest,
    ComparePlacesResponse,
    CompareRecommendResponse,
    ComparisonResult,
    EnhancedComparisonResult,
)
from app.services.comparison_service import ComparisonService

logger = logging.getLogger(__name__)


# ── Helper: map EnhancedComparisonResult → legacy ComparisonResult
def _legacy_mapping(places: List[EnhancedComparisonResult]) -> List[ComparisonResult]:
    """Convert new EnhancedComparisonResult list to legacy ComparisonResult list."""
    legacy = []
    for place in places:
        legacy.append(
            ComparisonResult(
                place_id=place.place_id,
                display_name=place.display_name,
                formatted_address=place.formatted_address,
                primary_type=place.primary_type,
                latitude=place.latitude,
                longitude=place.longitude,
                rating=place.rating,
                user_rating_count=place.user_rating_count,
                price_level=place.price_level,
                business_status=place.business_status,
                open_now=place.open_now,
                opening_hours_summary=place.opening_hours_summary,
                wheelchair_accessible=place.wheelchair_accessible,
                website_uri=place.website_uri,
                phone_number=place.phone_number,
                editorial_summary=place.editorial_summary,
                photo_name=(
                    place.photo_references[0].name if place.photo_references else None
                ),
                dine_in=place.dine_in,
                takeout=place.takeout,
                delivery=place.delivery,
                curbside_pickup=place.curbside_pickup,
                serves_breakfast=place.serves_breakfast,
                serves_lunch=place.serves_lunch,
                serves_dinner=place.serves_dinner,
                serves_brunch=place.serves_brunch,
                serves_beer=place.serves_beer,
                serves_wine=place.serves_wine,
                serves_cocktails=place.serves_cocktails,
                serves_vegetarian_food=place.serves_vegetarian_food,
                outdoor_seating=place.outdoor_seating,
                restroom=place.restroom,
                good_for_children=place.good_for_children,
                good_for_groups=place.good_for_groups,
                live_music=place.live_music,
                reservable=place.reservable,
                parking_free=place.parking_free,
                parking_paid=place.parking_paid,
                parking_valet=place.parking_valet,
                ev_charging=place.ev_charging,
                payment_cash=place.payment_cash,
                payment_credit_cards=place.payment_credit_cards,
                payment_contactless=place.payment_contactless,
                payment_nfc=place.payment_nfc,
                wikipedia_extract=place.wikipedia_extract,
                neighborhood=place.neighborhood,
            )
        )
    return legacy


router = APIRouter(prefix="/compare", tags=["Comparison"])


# API 1: POST /compare/basic — Side-by-Side Attribute Comparison
@router.post("/basic", response_model=CompareBasicResponse)
@limiter.limit("20/minute")
async def compare_basic(
    request: Request,
    body: ComparePlacesRequest,
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(get_comparison_service),
) -> CompareBasicResponse:
    result = await service.compare_basic(
        place_ids=body.place_ids,
        user_id=current_user.id,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result


# POST /compare/recommend — AI-Powered Ranking
@router.post("/recommend", response_model=CompareRecommendResponse)
@limiter.limit("20/minute")
async def compare_recommend(
    request: Request,
    body: ComparePlacesRequest,
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(get_comparison_service),
) -> CompareRecommendResponse:
    result = await service.recommend(
        place_ids=body.place_ids,
        user_id=current_user.id,
        use_ai_summary=True,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result


# LEGACY: POST /compare — Original flat comparison (kept for backward compat)
@router.post("", response_model=ComparePlacesResponse)
@limiter.limit("20/minute")
async def compare_places_legacy(
    request: Request,
    body: ComparePlacesRequest,
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(get_comparison_service),
) -> ComparePlacesResponse:
    basic = await service.compare_basic(
        place_ids=body.place_ids,
        user_id=current_user.id,
    )

    if not basic.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=basic.message,
        )

    return ComparePlacesResponse(
        success=True,
        message=basic.message,
        comparison=_legacy_mapping(basic.places),
        highlights=basic.highlights,
        total_places=basic.total_places,
    )


# LEGACY: GET /compare/batch — Original batch endpoint (kept for backward compat)
@router.get("/batch", response_model=ComparePlacesResponse)
@limiter.limit("20/minute")
async def compare_places_get_legacy(
    request: Request,
    ids: str = Query(
        ...,
        description="Comma-separated list of 2-10 place IDs",
        min_length=1,
    ),
    current_user: User = Depends(get_current_user),
    service: ComparisonService = Depends(get_comparison_service),
) -> ComparePlacesResponse:
    pids = [pid.strip() for pid in ids.split(",") if pid.strip()]
    if len(pids) < 2 or len(pids) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide between 2 and 10 comma-separated place IDs.",
        )

    basic = await service.compare_basic(
        place_ids=pids,
        user_id=current_user.id,
    )

    if not basic.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=basic.message,
        )

    return ComparePlacesResponse(
        success=True,
        message=basic.message,
        comparison=_legacy_mapping(basic.places),
        highlights=basic.highlights,
        total_places=basic.total_places,
    )
