"""
Pydantic schemas for the Place Photos layer.

Covers:
  GET /api/v1/places/{place_id}/photos
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class PhotoItem(BaseModel):
    """
    A single resolved photo — resource name plus a ready-to-use CDN URL.

    The frontend can use `url` directly in an <img src> tag.
    `photo_name` is included so the frontend can request a different
    size by calling the endpoint again with a different max_width_px.
    """

    photo_name: str = Field(
        description=(
            "Original Google resource name "
            "(e.g. 'places/ChIJ.../photos/AUac...'). "
            "Stable identifier for this photo."
        )
    )
    url: str = Field(
        description="CDN image URL — ready for direct use in <img src>."
    )
    max_width_px: int = Field(
        description="Width (px) the URL was resolved for."
    )


class PlacePhotosResponse(BaseModel):
    """Standard envelope for GET /api/v1/places/{place_id}/photos."""

    success: bool
    place_id: str
    message: str
    cached: bool = False
    total_photos: int
    data: List[PhotoItem]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
