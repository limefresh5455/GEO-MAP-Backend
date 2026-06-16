"""
PlacePhotosService — resolves photo URLs for a place.

Pipeline
--------
1. Look up the place in PostgreSQL (must exist — call Details API first).
2. Extract the list of photo resource names from place_details.photos (JSONB).
3. Check Redis cache — key: photo_urls:{place_id}:{max_width_px}
   TTL: 1 hour (photo CDN URLs are stable for a few hours).
4. On cache miss: call GooglePlacePhotosClient.resolve_photo_urls().
5. Write resolved URLs to Redis.
6. Return list of PhotoItem objects.

Design rules
------------
- This service is read-only — it never writes to the place_details table.
- It depends on place_details.photos already being populated, which
  happens automatically when PlaceDetailsService fetches from Google.
- Cache key includes max_width_px because the same photo resolved at
  different sizes produces different CDN URLs.
- Individual photo resolution failures are tolerated — the service returns
  whatever successfully resolved. A place with 5 photos where 1 fails
  returns 4 photos, not an error.
- Redis failures are logged but never crash the request (cache is advisory).
"""

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

# TTL: 1 hour — Google CDN URLs are stable for a few hours.
# Shorter than place_details TTL because photo URLs can expire.
_PHOTO_CACHE_TTL = 3600

# Hard cap — Google returns up to 10 photos in Place Details (New).
# We cap the resolve call to avoid unnecessary API calls.
_MAX_PHOTOS = 10


def _photo_cache_key(place_id: str, max_width_px: int) -> str:
    """Cache key is scoped to place_id + requested width."""
    return f"{_PHOTO_CACHE_PREFIX}:{place_id}:{max_width_px}"


class PlacePhotosService:
    """
    Resolves and caches photo URLs for a specific place.

    Parameters
    ----------
    db            : SQLAlchemy session (read-only usage)
    redis_repo    : RedisRepository for caching resolved URLs
    photos_client : GooglePlacePhotosClient with shared httpx pool
    """

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
        """
        Load place from DB and extract photo resource names from the
        JSONB photos column.

        Returns an empty list (not raises) if the place has no photos.
        Raises PlaceDetailNotFoundError if the place doesn't exist at all.
        """
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

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    async def get_place_photos(
        self,
        place_id: str,
        max_photos: int = 5,
        max_width_px: int = 800,
    ) -> PlacePhotosResponse:
        """
        Resolve and return photo URLs for a place.

        Parameters
        ----------
        place_id     : Google place ID (must exist in place_details table)
        max_photos   : maximum number of photos to return (1–10, default 5)
        max_width_px : CDN image width in pixels (default 800)

        Returns
        -------
        PlacePhotosResponse with a list of PhotoItem objects, each containing
        a ready-to-use CDN URL.

        Raises
        ------
        PlaceDetailNotFoundError   : if place is not in the local DB
                                     (call GET /places/{id}/details first)
        GooglePlacesRateLimitError : if Google returns 429
        GooglePlacesAPIError       : on auth/billing failure
        """
        # Clamp max_photos to valid range
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
        # This raises PlaceDetailNotFoundError if the place doesn't exist
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
        # Resolve all available names (up to _MAX_PHOTOS) and cache them all.
        # We cache the full set, not just max_photos, so that a later request
        # for a different count hits the cache instead of calling Google again.
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
