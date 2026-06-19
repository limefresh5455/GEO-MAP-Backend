from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.exceptions.custom_exceptions import LocationNotFoundError
from app.models.user import User
from app.schemas.location import (
    APIResponse,
    GPSUpdateRequest,
    LocationData,
    ManualUpdateRequest,
    PaginatedHistoryResponse,
)
from app.services.location_service import LocationService
router = APIRouter(prefix="/locations", tags=["Locations"])

def _service(db: Session = Depends(get_db)) -> LocationService:
    return LocationService(db)


@router.get("/me", response_model=APIResponse)
def get_my_location(
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """Get user's current active location."""
    location = service.get_current_location(current_user.id)
    return APIResponse(
        success=True,
        message="Current location retrieved",
        data=LocationData.model_validate(location),
    )


@router.post("/gps", response_model=APIResponse, status_code=status.HTTP_200_OK)
def gps_update(
    payload: GPSUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """    
    **Request body:**
    ```json
    {
      "latitude": 28.6304,
      "longitude": 77.2177,
      "accuracy": 10.0
    }
    ```
    """
    location, is_duplicate = service.process_gps_update(current_user.id, payload)

    if is_duplicate:
        return APIResponse(
            success=True,
            message="Location unchanged — duplicate update acknowledged",
            data=LocationData.model_validate(location),
        )

    return APIResponse(
        success=True,
        message="GPS location updated successfully",
        data=LocationData.model_validate(location),
    )


@router.put("/manual", response_model=APIResponse)
def manual_update(
    payload: ManualUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """
    Manually set location.
    
    **Request body:**
    ```json
    {
      "latitude": 28.6304,
      "longitude": 77.2177,
      "label": "Home"
    }
    ```
    """
    location = service.process_manual_update(current_user.id, payload)
    return APIResponse(
        success=True,
        message="Location manually updated",
        data=LocationData.model_validate(location),
    )


@router.get("/history", response_model=APIResponse)
def get_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """Get location history with pagination."""
    items, total = service.get_location_history(current_user.id, page, page_size)
    return APIResponse(
        success=True,
        message="Location history retrieved",
        data=PaginatedHistoryResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total,
        ),
    )


@router.get("/latest", response_model=APIResponse)
def get_latest(
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """Get most recent location record."""
    location = service.get_latest_location(current_user.id)
    return APIResponse(
        success=True,
        message="Latest location retrieved",
        data=LocationData.model_validate(location),
    )


@router.delete("/current", response_model=APIResponse)
def delete_current_location(
    current_user: User = Depends(get_current_user),
    service: LocationService = Depends(_service),
):
    """Deactivate current location (soft delete)."""
    found = service.deactivate_current_location(current_user.id)
    if not found:
        raise LocationNotFoundError()
    return APIResponse(
        success=True,
        message="Current location deactivated",
    )
