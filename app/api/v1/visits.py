import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.orm import Session
from app.core.rate_limiter import shared_limiter as limiter
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.visits import (
    DeleteVisitResponse,
    ListVisitsResponse,
    LogVisitActionResponse,
    LogVisitRequest,
    UpdateVisitRequest,
    VisitLogResponse,
    VisitStatsResponse,
)
from app.services.visit_service import VisitService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Places — Visit History"])


def get_service(db: Session = Depends(get_db)) -> VisitService:
    return VisitService(db)


@router.post("/places/{place_id}/visit", response_model=LogVisitActionResponse)
@limiter.limit("30/minute")
async def log_visit(
    request: Request,
    place_id: str = Path(..., min_length=1, max_length=255),
    payload: LogVisitRequest = ...,
    current_user: User = Depends(get_current_user),
    service: VisitService = Depends(get_service),
) -> LogVisitActionResponse:
    """Log a visit to a place with optional rating, review, and mood."""
    result = await service.log_visit(
        user_id=current_user.id,
        place_id=place_id,
        rating_given=payload.rating_given,
        review_text=payload.review_text,
        with_whom=payload.with_whom,
        mood=payload.mood,
    )
    return LogVisitActionResponse(
        message="Visit logged successfully!",
        place_id=place_id,
        visit_id=result.id,
    )


@router.get("/visits", response_model=ListVisitsResponse)
@limiter.limit("30/minute")
async def list_visits(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    place_id: Optional[str] = Query(None, description="Filter by place"),
    current_user: User = Depends(get_current_user),
    service: VisitService = Depends(get_service),
) -> ListVisitsResponse:
    """List visit history with pagination."""
    items, total, has_next = await service.list_visits(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        place_id=place_id,
    )
    return ListVisitsResponse(
        data=items,
        total_count=total,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.patch("/visits/{visit_id}", response_model=VisitLogResponse)
@limiter.limit("30/minute")
async def update_visit(
    request: Request,
    visit_id: int = Path(..., ge=1),
    payload: UpdateVisitRequest = ...,
    current_user: User = Depends(get_current_user),
    service: VisitService = Depends(get_service),
) -> VisitLogResponse:
    """Update a visit log entry (rating, review, mood)."""
    result = await service.update_visit(
        visit_id=visit_id,
        user_id=current_user.id,
        rating_given=payload.rating_given,
        review_text=payload.review_text,
        with_whom=payload.with_whom,
        mood=payload.mood,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit log entry not found.",
        )
    return result


@router.delete("/visits/{visit_id}", response_model=DeleteVisitResponse)
@limiter.limit("30/minute")
async def delete_visit(
    request: Request,
    visit_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    service: VisitService = Depends(get_service),
) -> DeleteVisitResponse:
    """Delete a visit log entry."""
    deleted = await service.delete_visit(visit_id=visit_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visit log entry not found.",
        )
    return DeleteVisitResponse(
        message="Visit log entry deleted.",
        visit_id=visit_id,
    )


@router.get("/visits/stats", response_model=VisitStatsResponse)
@limiter.limit("30/minute")
async def visit_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
    service: VisitService = Depends(get_service),
) -> VisitStatsResponse:
    """Get visit statistics (totals, by category, by month)."""
    stats = await service.get_stats(user_id=current_user.id)
    return VisitStatsResponse(**stats)
