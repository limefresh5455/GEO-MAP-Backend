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
_LOCK_TTL_SECONDS = 30
_LOCK_RETRY_INTERVAL = 0.3
_LOCK_MAX_RETRIES = 10


def _details_cache_key(place_id: str) -> str:
    return f"{_DETAILS_KEY_PREFIX}:{place_id}"


def _lock_key(place_id: str) -> str:
    return f"{_LOCK_KEY_PREFIX}:{place_id}"


def _orm_to_result(record) -> PlaceDetailResult:
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
        extended_data=record.extended_data,
        last_fetched_at=record.last_fetched_at,
        knowledge_synced=record.knowledge_synced,
    )


class PlaceDetailsService:
    """Fetch and cache place details from the Google Places API (New).

    Only the Google Place Details API is used for fresh data, with Redis + PG
    as a caching layer for performance. After fetching, a background task
    creates Pinecone vectors so the Place Q&A endpoint can answer questions.
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
        self.repo = PlaceDetailsRepository(db)
        self._details_ttl = settings.REDIS_DETAILS_CACHE_TTL
        self.knowledge_service = knowledge_service
        self._stale_after_days: int = getattr(settings, "DETAILS_STALE_AFTER_DAYS", 7)

    # ── Redis helpers ────────────────────────────────────────────────────

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
                "Place Details cache deserialisation error for %s: %s",
                place_id,
                exc,
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
                "Place Details cache write failed for %s: %s",
                detail.place_id,
                exc,
            )

    # ── Stampede lock ────────────────────────────────────────────────────

    async def _acquire_lock(self, place_id: str) -> bool:
        if self.redis_repo.client is None:
            return True
        try:
            key = _lock_key(place_id)
            acquired = await self.redis_repo.client.set(
                key, "1", nx=True, ex=_LOCK_TTL_SECONDS
            )
            return bool(acquired)
        except Exception as exc:
            logger.warning(
                "Lock acquire failed for %s: %s — proceeding without lock",
                place_id,
                exc,
            )
            return True

    async def _release_lock(self, place_id: str) -> None:
        if self.redis_repo.client is None:
            return
        try:
            await self.redis_repo.client.delete(_lock_key(place_id))
        except Exception as exc:
            logger.warning("Lock release failed for %s: %s", place_id, exc)

    # ── Background knowledge sync (Pinecone vectors for Place Q&A) ───────

    async def _trigger_background_knowledge_sync(self, place_id: str) -> None:
        """
        Automatically create Pinecone vectors after fetching place details.
        Runs as a fire-and-forget background task so the API response is not
        blocked by embedding + Pinecone upload.
        """
        if self.knowledge_service is None:
            logger.debug(
                "Knowledge sync skipped (no KnowledgeService injected) — "
                "place_id: %s",
                place_id,
            )
            return

        async def _sync_task():
            try:
                from app.schemas.knowledge import KnowledgeSyncRequest
                from app.database.connection import SessionLocal
                from app.services.knowledge_service import KnowledgeService

                task_db = SessionLocal()
                try:
                    logger.info(
                        "Background knowledge sync started — place_id: %s",
                        place_id,
                    )
                    task_knowledge_service = KnowledgeService(
                        db=task_db,
                        openai_client=self.knowledge_service.openai_client,
                        pinecone_client=self.knowledge_service.pinecone_client,
                    )
                    result = await task_knowledge_service.sync_place_knowledge(
                        place_id=place_id,
                        request=KnowledgeSyncRequest(force_resync=False),
                    )
                    if result.skipped:
                        logger.info(
                            "Background knowledge sync skipped "
                            "(already up-to-date) — place_id: %s",
                            place_id,
                        )
                    else:
                        logger.info(
                            "Background knowledge sync completed — "
                            "place_id: %s, vectors: %d",
                            place_id,
                            result.vector_count or 0,
                        )
                finally:
                    task_db.close()
            except Exception as exc:
                logger.warning(
                    "Background knowledge sync failed for place_id %s: %s",
                    place_id,
                    exc,
                )

        asyncio.create_task(_sync_task())
        logger.debug("Background knowledge sync task created — place_id: %s", place_id)

    # ── Google fetch (with stampede lock) ────────────────────────────────

    async def _fetch_from_google_with_lock(
        self, place_id: str
    ) -> Tuple[PlaceDetailResult, str]:
        acquired = await self._acquire_lock(place_id)

        if not acquired:
            # Another request is fetching — wait for it, then check cache
            for _ in range(_LOCK_MAX_RETRIES):
                await asyncio.sleep(_LOCK_RETRY_INTERVAL)
                cached = await self._try_get_from_cache(place_id)
                if cached is not None:
                    logger.info(
                        "Place Details stampede avoided — served from cache "
                        "after lock wait: place_id=%s",
                        place_id,
                    )
                    return cached, DetailSource.REDIS

            cached = await self._try_get_from_cache(place_id)
            if cached is not None:
                logger.info(
                    "Place Details found in cache after lock wait exhausted — "
                    "stampede avoided: place_id=%s",
                    place_id,
                )
                return cached, DetailSource.REDIS

            logger.warning(
                "Place Details lock wait exhausted for place_id=%s — "
                "calling Google directly as fallback",
                place_id,
            )

        try:
            # Re-check cache (TOCTOU mitigation)
            cached = await self._try_get_from_cache(place_id)
            if cached is not None:
                return cached, DetailSource.REDIS

            detail = await self.google_client.get_place_details(place_id)
            detail.last_fetched_at = datetime.now(timezone.utc)
            self.repo.upsert(detail)
            self.db.commit()
            logger.info("Place Details saved to DB — place_id: %s", place_id)

            await self._write_to_cache(detail)

            # Background knowledge sync — creates Pinecone vectors for Place Q&A
            await self._trigger_background_knowledge_sync(place_id)

            return detail, DetailSource.GOOGLE
        finally:
            if acquired:
                await self._release_lock(place_id)

    # ── Public entry point ───────────────────────────────────────────────

    async def get_place_details(self, place_id: str) -> Tuple[PlaceDetailResult, str]:
        # Tier 1: Redis cache
        cached = await self._try_get_from_cache(place_id)
        if cached is not None:
            return cached, DetailSource.REDIS

        logger.info("Place Details cache MISS — place_id: %s", place_id)

        # Tier 2: PostgreSQL
        db_record = self.repo.get_by_place_id(place_id)
        if db_record is not None:
            stale_threshold = datetime.now(timezone.utc) - timedelta(
                days=self._stale_after_days
            )
            last_fetched = db_record.last_fetched_at
            if last_fetched and last_fetched.tzinfo is None:
                last_fetched = last_fetched.replace(tzinfo=timezone.utc)

            if last_fetched and last_fetched < stale_threshold:
                logger.info(
                    "Place Details DB record stale (last_fetched=%s, "
                    "threshold=%s) — refreshing from Google: place_id=%s",
                    last_fetched,
                    stale_threshold,
                    place_id,
                )
                # Fall through to Google fetch
            else:
                logger.info(
                    "Place Details DB HIT — place_id: %s (last_fetched: %s)",
                    place_id,
                    db_record.last_fetched_at,
                )
                result = _orm_to_result(db_record)
                await self._write_to_cache(result)
                return result, DetailSource.DATABASE

        logger.info("Place Details DB MISS — place_id: %s → calling Google", place_id)

        # Tier 3: Google (with stampede lock)
        return await self._fetch_from_google_with_lock(place_id)
