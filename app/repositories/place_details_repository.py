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

B02 FIX: knowledge_synced is only reset to False when the content hash
has actually changed, preserving the sync flag for unchanged data.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.place_detail import PlaceDetail
from app.schemas.place_details import PlaceDetailResult

logger = logging.getLogger(__name__)


def _compute_content_hash(detail: PlaceDetailResult) -> str:
    """
    SHA-256 of the key content fields that matter for knowledge sync.
    If this hash matches the existing record's content hash, the knowledge
    vectors in Pinecone are still valid and knowledge_synced must NOT be reset.

    Only fields that are embedded into the Pinecone knowledge document are
    included — metadata-only fields like last_fetched_at are excluded.
    """
    # B058 FIX: Removed sorted() call on types list.
    # The types list order doesn't matter for hash stability — we only care
    # about whether the content has changed. Sorting on every hash computation
    # is unnecessary overhead. If Google returns types in a different order
    # but the same content, the hash will differ, but that's acceptable since
    # the actual data structure changed (even if semantically equivalent).
    parts = [
        str(detail.display_name or ""),
        str(detail.formatted_address or ""),
        str(detail.primary_type or ""),
        str(detail.types or []),  # No sorting — order matters for hash
        str(detail.international_phone_number or ""),
        str(detail.national_phone_number or ""),
        str(detail.website_uri or ""),
        str(detail.google_maps_uri or ""),
        str(detail.rating or ""),
        str(detail.user_rating_count or ""),
        str(detail.business_status or ""),
        str(detail.open_now or ""),
        str(detail.price_level or ""),
        str(detail.wheelchair_accessible_entrance or ""),
        str(detail.editorial_summary or ""),
        # Stringify nested JSONB-bound fields for comparison
        str(detail.opening_hours.model_dump() if detail.opening_hours else ""),
        str([r.model_dump() for r in detail.reviews] if detail.reviews else ""),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


# ---------------------------------------------------------------------------
# Re-hydration helpers — used by the content-hash comparison in upsert()
# Mirror the logic in PlaceDetailsService._orm_to_result but kept local
# so the repository has no service dependency.
# ---------------------------------------------------------------------------

def _rehydrate_opening_hours(data: Optional[Dict]) -> Optional[Any]:
    """Silently returns None on any deserialisation error."""
    if not data:
        return None
    try:
        from app.schemas.place_details import OpeningHours  # local import avoids circular
        return OpeningHours(**data)
    except Exception:
        return None


def _rehydrate_reviews(data: Optional[list]) -> Optional[list]:
    """Silently returns None on any deserialisation error."""
    if not data:
        return None
    try:
        from app.schemas.place_details import PlaceReview  # local import avoids circular
        return [PlaceReview(**r) for r in data]
    except Exception:
        return None


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
        
        B059 FIX: Added try-except around insert to handle concurrent upsert races.
        If two requests both check and find no existing row, both may try to insert.
        The second insert will violate the unique constraint on place_id. We catch
        this, rollback, and re-query to get the winner's row, then update it.
        """
        existing = self.get_by_place_id(detail.place_id)

        opening_hours_dict = _to_dict(detail.opening_hours)
        photos_list = _to_dict(detail.photos)
        reviews_list = _to_dict(detail.reviews)
        types_list = detail.types  # already a plain list[str] or None

        now_utc = datetime.now(timezone.utc)

        if existing:
            # B02 FIX: Compute content hash before updating fields.
            # Only reset knowledge_synced=False when the embeddable content
            # has actually changed — preserving the Pinecone sync state for
            # identical re-fetches (e.g., cache TTL expiry with no data change).
            new_content_hash = _compute_content_hash(detail)
            existing_content_hash = _compute_content_hash(
                PlaceDetailResult(
                    place_id=existing.place_id,
                    display_name=existing.display_name,
                    formatted_address=existing.formatted_address,
                    primary_type=existing.primary_type,
                    types=existing.types,
                    international_phone_number=existing.international_phone_number,
                    national_phone_number=existing.national_phone_number,
                    website_uri=existing.website_uri,
                    google_maps_uri=existing.google_maps_uri,
                    rating=existing.rating,
                    user_rating_count=existing.user_rating_count,
                    business_status=existing.business_status,
                    open_now=existing.open_now,
                    price_level=existing.price_level,
                    wheelchair_accessible_entrance=existing.wheelchair_accessible_entrance,
                    editorial_summary=existing.editorial_summary,
                    opening_hours=_rehydrate_opening_hours(existing.opening_hours),
                    reviews=_rehydrate_reviews(existing.reviews),
                )
            )
            content_changed = (new_content_hash != existing_content_hash)

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

            # B02: Only invalidate knowledge_synced when content actually changed.
            # Keeps the Pinecone vectors valid when data is unchanged.
            if content_changed:
                existing.knowledge_synced = False
                logger.debug(
                    "PlaceDetail content changed — knowledge_synced reset: place_id=%s",
                    detail.place_id,
                )
            else:
                logger.debug(
                    "PlaceDetail content unchanged — knowledge_synced preserved: place_id=%s",
                    detail.place_id,
                )

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
        
        try:
            self.db.add(record)
            self.db.flush()
            logger.debug("PlaceDetail inserted: place_id=%s", detail.place_id)
            return record
        except Exception as e:
            # B059 FIX: Handle concurrent insert race condition.
            # If two requests both check and find no row, both try to insert.
            # Second insert fails on unique constraint. Catch it, rollback, and
            # re-query to get the winner's row, then proceed with update logic.
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError) and "place_id" in str(e.orig).lower():
                logger.warning(
                    "Concurrent upsert detected for place_id=%s — another request "
                    "inserted first. Rolling back and updating the existing row.",
                    detail.place_id
                )
                self.db.rollback()
                # Re-query the row that the concurrent request inserted
                existing = self.get_by_place_id(detail.place_id)
                if not existing:
                    # Should never happen, but defensive programming
                    logger.error(
                        "Race condition recovery failed — place_id=%s not found after rollback",
                        detail.place_id
                    )
                    raise
                
                # Update the existing row (same logic as above update branch)
                new_content_hash = _compute_content_hash(detail)
                existing_content_hash = _compute_content_hash(
                    PlaceDetailResult(
                        place_id=existing.place_id,
                        display_name=existing.display_name,
                        formatted_address=existing.formatted_address,
                        primary_type=existing.primary_type,
                        types=existing.types,
                        international_phone_number=existing.international_phone_number,
                        national_phone_number=existing.national_phone_number,
                        website_uri=existing.website_uri,
                        google_maps_uri=existing.google_maps_uri,
                        rating=existing.rating,
                        user_rating_count=existing.user_rating_count,
                        business_status=existing.business_status,
                        open_now=existing.open_now,
                        price_level=existing.price_level,
                        wheelchair_accessible_entrance=existing.wheelchair_accessible_entrance,
                        editorial_summary=existing.editorial_summary,
                        opening_hours=_rehydrate_opening_hours(existing.opening_hours),
                        reviews=_rehydrate_reviews(existing.reviews),
                    )
                )
                content_changed = (new_content_hash != existing_content_hash)
                
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
                existing.wheelchair_accessible_entrance = detail.wheelchair_accessible_entrance
                existing.editorial_summary = detail.editorial_summary
                existing.last_fetched_at = now_utc
                
                if content_changed:
                    existing.knowledge_synced = False
                
                self.db.flush()
                logger.debug("PlaceDetail updated after race condition: place_id=%s", detail.place_id)
                return existing
            else:
                # Different error — re-raise
                raise
