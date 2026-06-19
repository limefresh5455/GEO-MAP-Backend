from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class GPSUpdateRequest(BaseModel):
    """Payload sent by the mobile/web client for automatic GPS updates."""

    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy: Optional[float] = Field(None, ge=0)
    altitude: Optional[float] = None
    speed: Optional[float] = Field(None, ge=0)
    client_timestamp: Optional[datetime] = None
    metadata_notes: Optional[str] = Field(None, max_length=500)


class ManualUpdateRequest(BaseModel):
    """Payload for a user-initiated manual location update."""

    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy: Optional[float] = Field(None, ge=0)
    altitude: Optional[float] = None
    metadata_notes: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class LocationData(BaseModel):
    id: int
    user_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float]
    altitude: Optional[float]
    speed: Optional[float]
    source: str
    is_current: bool
    client_timestamp: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    metadata_notes: Optional[str]

    model_config = {"from_attributes": True}


class LocationHistoryItem(BaseModel):
    id: int
    user_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float]
    altitude: Optional[float]
    speed: Optional[float]
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedHistoryResponse(BaseModel):
    items: List[LocationHistoryItem]
    total: int
    page: int
    page_size: int
    has_next: bool


class APIResponse(BaseModel):
    """Standard envelope for all location API responses."""

    success: bool
    message: str
    data: Optional[Any] = None
    errors: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
