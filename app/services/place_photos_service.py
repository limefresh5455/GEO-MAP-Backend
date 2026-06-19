import json
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.exceptions.places import PlaceDetailNotFoundError
from app.integrations.google_place_photos import GooglePlacePhotosClient
from app.repositories.place_details_repository import PlaceDetailsRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.place_photos import PhotoItem, PlacePhotosResponse

logger = logging.getLogger(__name__)

# Redis key prefix for resolved photo URLs
_PHOTO_CACHE_PREFIX = "photo_urls"


_PHOTO_CACHE_TTL = 3600
_MAX_PHOTOS = 10

def _photo_cache_key(place_id: str, max_width_px: int) -> str:
    """Cache key is scoped to place_id + requested width."""
    return f"{_PHOTO_CACHE_PREFIX}:{place_id}:{max_width_px}"


class PlacePhotosService:
    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        photos_client: GooglePlacePhotosClient,
    ) -> None:
        self._db = db
        self._redis = redis_repo
        self._client = photos_client
        self._repo = PlaceDetailsRepository(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_photo_names(self, place_id: str) -> List[str]:
        record = self._repo.get_by_place_id(place_id)
        if record is None:
            raise PlaceDetailNotFoundError(place_id)

        raw_photos = record.photos  # JSONB → list of dicts or None
        if not raw_photos or not isinstance(raw_photos, list):
            logger.info("No photos stored for place_id: %s", place_id)
            return []

        names = []
        for photo in raw_photos:
            if isinstance(photo, dict):
                name = photo.get("name")
                if name:
                    names.append(name)

        logger.info(
            "Extracted %d photo names from DB for place_id: %s",
            len(names), place_id,
        )
        return names[:_MAX_PHOTOS]

    async def _try_get_cache(
        self, cache_key: str
    ) -> Optional[List[PhotoItem]]:
        """Return cached PhotoItem list or None. Never raises."""
        raw = await self._redis.get(cache_key)
        if raw is None:
            return None
        try:
            # raw is already a Python list (RedisRepository deserialises JSON)
            items = [PhotoItem(**item) for item in raw]
            logger.info("Photo URL cache HIT — key: %s", cache_key)
            return items
        except Exception as exc:
            logger.warning(
                "Photo URL cache deserialisation failed (%s): %s",
                cache_key, exc,
            )
            return None

    async def _try_set_cache(
        self, cache_key: str, items: List[PhotoItem]
    ) -> None:
        """Write photo items to Redis. Never raises."""
        try:
            serialisable = [item.model_dump() for item in items]
            await self._redis.set(cache_key, serialisable, ttl=_PHOTO_CACHE_TTL)
        except Exception as exc:
            logger.warning(
                "Photo URL cache write failed (%s): %s", cache_key, exc
            )

    # Public: main entry point
    async def get_place_photos(
        self,
        place_id: str,
        max_photos: int = 5,
        max_width_px: int = 800,
    ) -> PlacePhotosResponse:
        max_photos = max(1, min(max_photos, _MAX_PHOTOS))

        # ---- Step 1: Check Redis cache ----
        cache_key = _photo_cache_key(place_id, max_width_px)
        cached_items = await self._try_get_cache(cache_key)
        if cached_items is not None:
            # Slice to requested max_photos (cache may have stored up to 10)
            sliced = cached_items[:max_photos]
            return PlacePhotosResponse(
                success=True,
                place_id=place_id,
                message=f"{len(sliced)} photo(s) returned from cache",
                cached=True,
                total_photos=len(sliced),
                data=sliced,
            )

        # ---- Step 2: Extract photo names from DB ----
        all_names = self._extract_photo_names(place_id)

        if not all_names:
            return PlacePhotosResponse(
                success=True,
                place_id=place_id,
                message="This place has no photos available",
                cached=False,
                total_photos=0,
                data=[],
            )

        # ---- Step 3: Resolve URLs via Google Photos API ----
        logger.info(
            "Photo URL cache MISS — resolving %d photos for place_id: %s",
            len(all_names), place_id,
        )
        resolved = await self._client.resolve_photo_urls(
            photo_names=all_names,
            max_width_px=max_width_px,
        )

        # ---- Step 4: Build PhotoItem list ----
        items = [
            PhotoItem(
                photo_name=r["photo_name"],
                url=r["url"],
                max_width_px=r["max_width_px"],
            )
            for r in resolved
        ]

        # ---- Step 5: Write all resolved photos to Redis ----
        await self._try_set_cache(cache_key, items)

        # ---- Step 6: Return slice up to max_photos ----
        sliced = items[:max_photos]
        return PlacePhotosResponse(
            success=True,
            place_id=place_id,
            message=f"{len(sliced)} photo(s) resolved from Google",
            cached=False,
            total_photos=len(sliced),
            data=sliced,
        )
