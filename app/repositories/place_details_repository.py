"""
PlaceDetailsRepository — all PostgreSQL operations for the place_details table.

Rules
-----
- Upsert pattern: if the place already exists, update it in place.
  This keeps one canonical row per place_id — no duplicates.
- The repository never commits — the service owns the transaction.
- JSONB fields (types, opening_hours, photos, reviews) are serialised
  to plain Python dicts/lists before storage so SQLAlchemy / psycopg2
  can handle them without extra type adapters.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.place_detail import PlaceDetail
from app.schemas.place_details import PlaceDetailResult

logger = logging.getLogger(__name__)


def _to_dict(obj: Any) -> Any:
    """
    Recursively convert Pydantic models inside lists/dicts to plain dicts
    so they are safe to store in JSONB columns.
    """
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if hasattr(obj, "model_dump"):          # Pydantic v2
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


class PlaceDetailsRepository:
    """
    Handles upserts and reads for the place_details table.
    All writes are flushed (not committed) — the caller owns the transaction.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_place_id(self, place_id: str) -> Optional[PlaceDetail]:
        """Return the stored record for a place_id, or None if absent."""
        return (
            self.db.query(PlaceDetail)
            .filter(PlaceDetail.place_id == place_id)
            .first()
        )

    def mark_knowledge_synced(self, place_id: str) -> bool:
        """
        Set knowledge_synced = True for a place.
        Called by Phase 3 after a successful Pinecone upsert.
        Returns True if the row existed and was updated.
        """
        updated = (
            self.db.query(PlaceDetail)
            .filter(PlaceDetail.place_id == place_id)
            .update({"knowledge_synced": True}, synchronize_session=False)
        )
        return updated > 0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert(self, detail: PlaceDetailResult) -> PlaceDetail:
        """
        Insert or update the canonical place record.

        - If a row with this place_id exists: update all scalar and JSONB
          fields, bump last_fetched_at, and reset knowledge_synced to False
          (the new data may differ from what Pinecone has indexed).
        - If no row exists: insert a fresh record.

        Returns the ORM object (flushed, not committed).
        """
        existing = self.get_by_place_id(detail.place_id)

        opening_hours_dict = _to_dict(detail.opening_hours)
        photos_list = _to_dict(detail.photos)
        reviews_list = _to_dict(detail.reviews)
        types_list = detail.types  # already a plain list[str] or None

        now_utc = datetime.now(timezone.utc)

        if existing:
            # Update in place — upsert semantics
            existing.display_name = detail.display_name
            existing.formatted_address = detail.formatted_address
            existing.latitude = detail.latitude
            existing.longitude = detail.longitude
            existing.primary_type = detail.primary_type
            existing.types = types_list
            existing.international_phone_number = detail.international_phone_number
            existing.national_phone_number = detail.national_phone_number
            existing.website_uri = detail.website_uri
            existing.google_maps_uri = detail.google_maps_uri
            existing.rating = detail.rating
            existing.user_rating_count = detail.user_rating_count
            existing.business_status = detail.business_status
            existing.opening_hours = opening_hours_dict
            existing.open_now = detail.open_now
            existing.photos = photos_list
            existing.reviews = reviews_list
            existing.price_level = detail.price_level
            existing.wheelchair_accessible_entrance = (
                detail.wheelchair_accessible_entrance
            )
            existing.editorial_summary = detail.editorial_summary
            existing.last_fetched_at = now_utc
            # Reset sync flag — fresh data may differ from Pinecone index
            existing.knowledge_synced = False
            self.db.flush()
            logger.debug("PlaceDetail updated: place_id=%s", detail.place_id)
            return existing

        # Insert new record
        record = PlaceDetail(
            place_id=detail.place_id,
            display_name=detail.display_name,
            formatted_address=detail.formatted_address,
            latitude=detail.latitude,
            longitude=detail.longitude,
            primary_type=detail.primary_type,
            types=types_list,
            international_phone_number=detail.international_phone_number,
            national_phone_number=detail.national_phone_number,
            website_uri=detail.website_uri,
            google_maps_uri=detail.google_maps_uri,
            rating=detail.rating,
            user_rating_count=detail.user_rating_count,
            business_status=detail.business_status,
            opening_hours=opening_hours_dict,
            open_now=detail.open_now,
            photos=photos_list,
            reviews=reviews_list,
            price_level=detail.price_level,
            wheelchair_accessible_entrance=detail.wheelchair_accessible_entrance,
            editorial_summary=detail.editorial_summary,
            last_fetched_at=now_utc,
            knowledge_synced=False,
        )
        self.db.add(record)
        self.db.flush()
        logger.debug("PlaceDetail inserted: place_id=%s", detail.place_id)
        return record
