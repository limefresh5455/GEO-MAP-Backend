import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from app.models.place_detail import PlaceDetail
from app.schemas.place_details import PlaceDetailResult

logger = logging.getLogger(__name__)


def _compute_content_hash(detail: PlaceDetailResult) -> str:
    parts = [
        str(detail.display_name or ""),
        str(detail.formatted_address or ""),
        str(detail.primary_type or ""),
        str(sorted(detail.types) if detail.types else []),
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
        str(detail.extended_data or ""),
        str(detail.opening_hours.model_dump() if detail.opening_hours else ""),
        str([r.model_dump() for r in detail.reviews] if detail.reviews else ""),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def _rehydrate_opening_hours(data: Optional[Dict]) -> Optional[Any]:
    if not data:
        return None
    try:
        from app.schemas.place_details import (
            OpeningHours,
        )

        return OpeningHours(**data)
    except (ValueError, TypeError, KeyError):
        return None


def _rehydrate_reviews(data: Optional[list]) -> Optional[list]:
    if not data:
        return None
    try:
        from app.schemas.place_details import (
            PlaceReview,
        )

        return [PlaceReview(**r) for r in data]
    except (ValueError, TypeError, KeyError):
        return None


class PlaceDetailsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # Reads

    def get_by_place_id(self, place_id: str) -> Optional[PlaceDetail]:
        return (
            self.db.query(PlaceDetail).filter(PlaceDetail.place_id == place_id).first()
        )

    def mark_knowledge_synced(self, place_id: str) -> bool:
        updated = (
            self.db.query(PlaceDetail)
            .filter(PlaceDetail.place_id == place_id)
            .update({"knowledge_synced": True}, synchronize_session=False)
        )
        return updated > 0

    def _apply_detail_to_record(
        self,
        record: PlaceDetail,
        detail: PlaceDetailResult,
        content_changed: bool,
        now_utc: datetime,
    ) -> None:
        record.display_name = detail.display_name
        record.formatted_address = detail.formatted_address
        record.latitude = detail.latitude
        record.longitude = detail.longitude
        record.primary_type = detail.primary_type
        record.types = detail.types
        record.international_phone_number = detail.international_phone_number
        record.national_phone_number = detail.national_phone_number
        record.website_uri = detail.website_uri
        record.google_maps_uri = detail.google_maps_uri
        record.rating = detail.rating
        record.user_rating_count = detail.user_rating_count
        record.business_status = detail.business_status
        record.opening_hours = _to_dict(detail.opening_hours)
        record.open_now = detail.open_now
        record.photos = _to_dict(detail.photos)
        record.reviews = _to_dict(detail.reviews)
        record.price_level = detail.price_level
        record.wheelchair_accessible_entrance = detail.wheelchair_accessible_entrance
        record.editorial_summary = detail.editorial_summary
        record.extended_data = detail.extended_data
        record.last_fetched_at = now_utc

        if content_changed:
            record.knowledge_synced = False

    def _compute_hash_for_record(self, record: PlaceDetail) -> str:
        return _compute_content_hash(
            PlaceDetailResult(
                place_id=record.place_id,
                display_name=record.display_name,
                formatted_address=record.formatted_address,
                primary_type=record.primary_type,
                types=record.types,
                international_phone_number=record.international_phone_number,
                national_phone_number=record.national_phone_number,
                website_uri=record.website_uri,
                google_maps_uri=record.google_maps_uri,
                rating=record.rating,
                user_rating_count=record.user_rating_count,
                business_status=record.business_status,
                open_now=record.open_now,
                price_level=record.price_level,
                wheelchair_accessible_entrance=record.wheelchair_accessible_entrance,
                editorial_summary=record.editorial_summary,
                opening_hours=_rehydrate_opening_hours(record.opening_hours),
                reviews=_rehydrate_reviews(record.reviews),
            )
        )

    def upsert(self, detail: PlaceDetailResult) -> PlaceDetail:
        existing = self.get_by_place_id(detail.place_id)

        types_list = detail.types

        now_utc = datetime.now(timezone.utc)

        if existing:
            new_content_hash = _compute_content_hash(detail)
            existing_content_hash = self._compute_hash_for_record(existing)
            content_changed = new_content_hash != existing_content_hash

            self._apply_detail_to_record(existing, detail, content_changed, now_utc)

            if content_changed:
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
            opening_hours=_to_dict(detail.opening_hours),
            open_now=detail.open_now,
            photos=_to_dict(detail.photos),
            reviews=_to_dict(detail.reviews),
            price_level=detail.price_level,
            wheelchair_accessible_entrance=detail.wheelchair_accessible_entrance,
            editorial_summary=detail.editorial_summary,
            extended_data=detail.extended_data,
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
            from sqlalchemy.exc import IntegrityError

            if isinstance(e, IntegrityError) and "place_id" in str(e.orig).lower():
                logger.warning(
                    "Concurrent upsert detected for place_id=%s — another request "
                    "inserted first. Rolling back and updating the existing row.",
                    detail.place_id,
                )
                self.db.rollback()
                # Re-query the row that the concurrent request inserted
                existing = self.get_by_place_id(detail.place_id)
                if not existing:
                    logger.error(
                        "Race condition recovery failed — place_id=%s not found after rollback",
                        detail.place_id,
                    )
                    raise

                # Use shared method for update logic
                new_content_hash = _compute_content_hash(detail)
                existing_content_hash = self._compute_hash_for_record(existing)
                content_changed = new_content_hash != existing_content_hash

                self._apply_detail_to_record(existing, detail, content_changed, now_utc)

                self.db.flush()
                logger.debug(
                    "PlaceDetail updated after race condition: place_id=%s",
                    detail.place_id,
                )
                return existing
            else:
                # Different error — re-raise
                raise
