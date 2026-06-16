import asyncio
import logging
from datetime import datetime, timedelta, timezone
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

_DETAILS_KEY_PREFIX = "place_details"
_LOCK_KEY_PREFIX = "place_details_lock"
# B11: Lock TTL — how long a "fetching in progress" lock is held (seconds)
_LOCK_TTL_SECONDS = 30
# B11: How long to wait between lock-check retries (seconds)
_LOCK_RETRY_INTERVAL = 0.3
# B11: Max retries before giving up and calling Google directly
_LOCK_MAX_RETRIES = 10


def _details_cache_key(place_id: str) -> str:
    return f"{_DETAILS_KEY_PREFIX}:{place_id}"


def _lock_key(place_id: str) -> str:
    return f"{_LOCK_KEY_PREFIX}:{place_id}"


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

    Phase 3: Optionally accepts a KnowledgeService to enable automatic
    background knowledge sync after fetching from Google.

    Returns (PlaceDetailResult, source_label).
    """

    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        google_client: GooglePlaceDetailsClient,
        knowledge_service=None,  # Optional[KnowledgeService] — avoid circular import
    ) -> None:
        self.db = db
        self.redis_repo = redis_repo
        self.google_client = google_client
        self.knowledge_service = knowledge_service
        self.repo = PlaceDetailsRepository(db)
        self._details_ttl = settings.REDIS_DETAILS_CACHE_TTL
        # B17: Re-fetch from Google if the DB record is older than this
        self._stale_after_days: int = getattr(settings, "DETAILS_STALE_AFTER_DAYS", 7)
        # Phase 3: Auto-sync knowledge after fetching from Google
        self._auto_sync_enabled: bool = getattr(
            settings, "AUTO_SYNC_KNOWLEDGE_ON_DETAILS_FETCH", True
        )

    # ------------------------------------------------------------------
    # Internal: Redis helpers
    # ------------------------------------------------------------------

    async def _try_get_from_cache(self, place_id: str) -> Optional[PlaceDetailResult]:
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
                "Place Details cache deserialisation error for %s: %s", place_id, exc
            )
            return None

    async def _write_to_cache(self, detail: PlaceDetailResult) -> None:
        key = _details_cache_key(detail.place_id)
        try:
            await self.redis_repo.set(
                key, detail.model_dump(mode="json"), ttl=self._details_ttl
            )
        except Exception as exc:
            logger.warning(
                "Place Details cache write failed for %s: %s", detail.place_id, exc
            )

    async def _acquire_lock(self, place_id: str) -> bool:
        """
        B11: Try to acquire a SET NX lock for this place_id.
        Returns True if the lock was acquired (this request is the "winner").
        Returns False if another request already holds the lock.
        """
        if self.redis_repo.client is None:
            return True  # No Redis — skip locking, allow direct Google call
        try:
            key = _lock_key(place_id)
            acquired = await self.redis_repo.client.set(
                key, "1", nx=True, ex=_LOCK_TTL_SECONDS
            )
            return bool(acquired)
        except Exception as exc:
            logger.warning("Lock acquire failed for %s: %s — proceeding without lock", place_id, exc)
            return True  # Fail open: allow Google call rather than block

    async def _release_lock(self, place_id: str) -> None:
        """B11: Release the fetch lock after writing to cache."""
        if self.redis_repo.client is None:
            return
        try:
            await self.redis_repo.client.delete(_lock_key(place_id))
        except Exception as exc:
            logger.warning("Lock release failed for %s: %s", place_id, exc)

    async def _trigger_background_knowledge_sync(self, place_id: str) -> None:
        """
        Phase 3: Fire-and-forget knowledge sync after fetching place details.

        This method creates an asyncio background task that syncs knowledge
        to Pinecone without blocking the place details response. Failures
        are logged but do not affect the details fetch flow.

        Why background sync?
        --------------------
        - Place details API remains fast (no waiting for embedding + Pinecone)
        - Users can immediately ask questions without manual sync step
        - Sync failures don't break the details fetch
        - Idempotent — if data unchanged, sync skips automatically

        The background task uses the same DB session pattern as the sync
        endpoint, creating a fresh session to avoid threading issues.
        """
        if not self._auto_sync_enabled:
            logger.debug(
                "Auto knowledge sync disabled — place_id: %s", place_id
            )
            return

        if self.knowledge_service is None:
            logger.debug(
                "Auto knowledge sync skipped (no KnowledgeService injected) — "
                "place_id: %s", place_id
            )
            return

        async def _sync_task():
            try:
                from app.schemas.knowledge import KnowledgeSyncRequest
                
                logger.info(
                    "Background knowledge sync started — place_id: %s", place_id
                )
                result = await self.knowledge_service.sync_place_knowledge(
                    place_id=place_id,
                    request=KnowledgeSyncRequest(force_resync=False),
                )
                if result.skipped:
                    logger.info(
                        "Background knowledge sync skipped (already up-to-date) — "
                        "place_id: %s", place_id
                    )
                else:
                    logger.info(
                        "Background knowledge sync completed — place_id: %s, "
                        "vectors: %d", place_id, result.vector_count or 0
                    )
            except Exception as exc:
                # Log but don't raise — this is fire-and-forget
                logger.warning(
                    "Background knowledge sync failed for place_id %s: %s",
                    place_id, exc
                )

        # Create background task (runs independently of the main response)
        asyncio.create_task(_sync_task())
        logger.debug(
            "Background knowledge sync task created — place_id: %s", place_id
        )

    async def _fetch_from_google_with_lock(
        self, place_id: str
    ) -> Tuple[PlaceDetailResult, str]:
        """
        B11: Acquire a lock before calling Google. If another request
        already holds the lock, wait and re-check the cache.
        """
        acquired = await self._acquire_lock(place_id)

        if not acquired:
            # Another request is fetching — wait for it then check cache
            for _ in range(_LOCK_MAX_RETRIES):
                await asyncio.sleep(_LOCK_RETRY_INTERVAL)
                cached = await self._try_get_from_cache(place_id)
                if cached is not None:
                    logger.info(
                        "Place Details stampede avoided — served from cache "
                        "after lock wait: place_id=%s", place_id
                    )
                    return cached, DetailSource.REDIS
            
            # B048 FIX: Final cache check after exhausting retries before calling Google.
            # The lock holder may have just written to cache as we were exiting the retry loop.
            cached = await self._try_get_from_cache(place_id)
            if cached is not None:
                logger.info(
                    "Place Details found in cache after lock wait exhausted — "
                    "stampede avoided: place_id=%s", place_id
                )
                return cached, DetailSource.REDIS
            
            # Lock holder timed out or cache write failed — fall through to Google
            logger.warning(
                "Place Details lock wait exhausted for place_id=%s — "
                "calling Google directly as fallback", place_id
            )

        try:
            # Re-check cache in case the lock holder just wrote while we
            # were acquiring (TOCTOU mitigation)
            cached = await self._try_get_from_cache(place_id)
            if cached is not None:
                return cached, DetailSource.REDIS

            detail = await self.google_client.get_place_details(place_id)
            detail.last_fetched_at = datetime.now(timezone.utc)
            self.repo.upsert(detail)
            self.db.commit()
            logger.info("Place Details saved to DB — place_id: %s", place_id)
            await self._write_to_cache(detail)
            
            # Phase 3: Trigger background knowledge sync after successful fetch
            await self._trigger_background_knowledge_sync(place_id)
            
            return detail, DetailSource.GOOGLE
        finally:
            if acquired:
                await self._release_lock(place_id)

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    async def get_place_details(
        self, place_id: str
    ) -> Tuple[PlaceDetailResult, str]:
        """
        Fetch full place details via the three-tier priority chain.
        """
        # Tier 1: Redis cache
        cached = await self._try_get_from_cache(place_id)
        if cached is not None:
            return cached, DetailSource.REDIS

        logger.info("Place Details cache MISS — place_id: %s", place_id)

        # Tier 2: PostgreSQL
        db_record = self.repo.get_by_place_id(place_id)
        if db_record is not None:
            # B17: Check staleness — re-fetch from Google if data is too old
            stale_threshold = datetime.now(timezone.utc) - timedelta(days=self._stale_after_days)
            last_fetched = db_record.last_fetched_at
            # Make last_fetched timezone-aware if it isn't (defensive)
            if last_fetched and last_fetched.tzinfo is None:
                last_fetched = last_fetched.replace(tzinfo=timezone.utc)

            if last_fetched and last_fetched < stale_threshold:
                logger.info(
                    "Place Details DB record stale (last_fetched=%s, threshold=%s) "
                    "— refreshing from Google: place_id=%s",
                    last_fetched, stale_threshold, place_id,
                )
                # Fall through to Google fetch below
            else:
                logger.info(
                    "Place Details DB HIT — place_id: %s (last_fetched: %s)",
                    place_id, db_record.last_fetched_at,
                )
                result = _orm_to_result(db_record)
                await self._write_to_cache(result)
                return result, DetailSource.DATABASE

        logger.info("Place Details DB MISS — place_id: %s → calling Google", place_id)

        # Tier 3: Google (with B11 stampede lock)
        return await self._fetch_from_google_with_lock(place_id)
