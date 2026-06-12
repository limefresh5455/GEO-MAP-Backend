"""
PlaceDetailsService — orchestrates the Place Details fetch pipeline.

Priority order (cache-aside + DB-fallback pattern):
  1. Redis cache  (key: place_details:{place_id}, TTL: 24 hours)
     → Fast path, no DB or Google call needed.
  2. PostgreSQL   (place_details table)
     → Warm path, saves a Google API call for recently fetched places.
       Refreshes Redis TTL on every DB hit.
  3. Google Place Details API
     → Cold path, called only on a full miss.
       Saves result to PostgreSQL and caches in Redis.

Design rules
------------
- The service NEVER calls db.commit() inside cache reads; commits only
  happen after a successful Google fetch + DB upsert.
- Redis failures are logged and swallowed — cache is advisory, never fatal.
- The PlaceDetailResult returned is always built from the freshest source
  in the priority chain above.
- `last_fetched_at` on the DB row tells downstream services (Phase 3)
  how stale the data is so they can decide whether to re-fetch.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.integrations.google_place_details import GooglePlaceDetailsClient
from app.repositories.place_details_repository import PlaceDetailsRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.place_details import (
    DetailSource,
    OpeningHours,
    PlaceDetailResult,
    PlacePhoto,
    PlaceReview,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Redis key prefix for place details — differs from search keys
_DETAILS_KEY_PREFIX = "place_details"


def _details_cache_key(place_id: str) -> str:
    """Deterministic Redis key for a place detail record."""
    return f"{_DETAILS_KEY_PREFIX}:{place_id}"


def _orm_to_result(record) -> PlaceDetailResult:
    """
    Convert a PlaceDetail ORM row back to a PlaceDetailResult schema object.
    Handles JSONB → Pydantic re-hydration for nested fields.
    """

    def _rehydrate_opening_hours(data: Optional[dict]) -> Optional[OpeningHours]:
        if not data:
            return None
        try:
            return OpeningHours(**data)
        except Exception:
            return None

    def _rehydrate_photos(data: Optional[list]) -> Optional[list]:
        if not data:
            return None
        try:
            return [PlacePhoto(**p) for p in data]
        except Exception:
            return None

    def _rehydrate_reviews(data: Optional[list]) -> Optional[list]:
        if not data:
            return None
        try:
            return [PlaceReview(**r) for r in data]
        except Exception:
            return None

    return PlaceDetailResult(
        place_id=record.place_id,
        display_name=record.display_name,
        formatted_address=record.formatted_address,
        latitude=record.latitude,
        longitude=record.longitude,
        primary_type=record.primary_type,
        types=record.types,
        international_phone_number=record.international_phone_number,
        national_phone_number=record.national_phone_number,
        website_uri=record.website_uri,
        google_maps_uri=record.google_maps_uri,
        rating=record.rating,
        user_rating_count=record.user_rating_count,
        business_status=record.business_status,
        opening_hours=_rehydrate_opening_hours(record.opening_hours),
        open_now=record.open_now,
        photos=_rehydrate_photos(record.photos),
        reviews=_rehydrate_reviews(record.reviews),
        price_level=record.price_level,
        wheelchair_accessible_entrance=record.wheelchair_accessible_entrance,
        editorial_summary=record.editorial_summary,
        last_fetched_at=record.last_fetched_at,
        knowledge_synced=record.knowledge_synced,
    )


class PlaceDetailsService:
    """
    Resolves a place_id to a full PlaceDetailResult through the
    Redis → PostgreSQL → Google priority chain.

    Returns (PlaceDetailResult, source_label) where source_label is one of
    the DetailSource constants ("redis_cache", "database", "google_places").
    """

    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        google_client: GooglePlaceDetailsClient,
    ) -> None:
        self.db = db
        self.redis_repo = redis_repo
        self.google_client = google_client
        self.repo = PlaceDetailsRepository(db)
        self._details_ttl = settings.REDIS_DETAILS_CACHE_TTL

    # ------------------------------------------------------------------
    # Internal: Redis helpers
    # ------------------------------------------------------------------

    async def _try_get_from_cache(
        self, place_id: str
    ) -> Optional[PlaceDetailResult]:
        key = _details_cache_key(place_id)
        raw = await self.redis_repo.get(key)
        if raw is None:
            return None
        try:
            result = PlaceDetailResult(**raw)
            logger.info("Place Details cache HIT — place_id: %s", place_id)
            return result
        except Exception as exc:
            logger.warning(
                "Place Details cache deserialisation error for %s: %s",
                place_id, exc,
            )
            return None

    async def _write_to_cache(self, detail: PlaceDetailResult) -> None:
        key = _details_cache_key(detail.place_id)
        try:
            await self.redis_repo.set(
                key,
                detail.model_dump(mode="json"),
                ttl=self._details_ttl,
            )
        except Exception as exc:
            logger.warning(
                "Place Details cache write failed for %s: %s",
                detail.place_id, exc,
            )

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    async def get_place_details(
        self, place_id: str
    ) -> Tuple[PlaceDetailResult, str]:
        """
        Fetch full place details via the three-tier priority chain.

        Returns
        -------
        (PlaceDetailResult, source)
            source is "redis_cache", "database", or "google_places"

        Raises
        ------
        PlaceDetailNotFoundError    — place_id not found anywhere
        GooglePlacesAPIError        — Google returned an error
        GooglePlacesRateLimitError  — rate limit hit
        GooglePlacesTimeoutError    — Google timed out
        """

        # ----------------------------------------------------------
        # Tier 1: Redis cache
        # ----------------------------------------------------------
        cached = await self._try_get_from_cache(place_id)
        if cached is not None:
            return cached, DetailSource.REDIS

        logger.info("Place Details cache MISS — place_id: %s", place_id)

        # ----------------------------------------------------------
        # Tier 2: PostgreSQL
        # ----------------------------------------------------------
        db_record = self.repo.get_by_place_id(place_id)
        if db_record is not None:
            logger.info(
                "Place Details DB HIT — place_id: %s (last_fetched: %s)",
                place_id,
                db_record.last_fetched_at,
            )
            result = _orm_to_result(db_record)
            # Refresh Redis so the next request hits cache
            await self._write_to_cache(result)
            return result, DetailSource.DATABASE

        logger.info(
            "Place Details DB MISS — place_id: %s → calling Google", place_id
        )

        # ----------------------------------------------------------
        # Tier 3: Google Place Details API
        # ----------------------------------------------------------
        # Raises PlaceDetailNotFoundError / GooglePlacesAPIError etc. on failure
        detail = await self.google_client.get_place_details(place_id)

        # Stamp fetch time before persisting
        detail.last_fetched_at = datetime.now(timezone.utc)

        # Persist to PostgreSQL (upsert)
        self.repo.upsert(detail)
        self.db.commit()
        logger.info(
            "Place Details saved to DB — place_id: %s", place_id
        )

        # Write to Redis
        await self._write_to_cache(detail)

        return detail, DetailSource.GOOGLE
