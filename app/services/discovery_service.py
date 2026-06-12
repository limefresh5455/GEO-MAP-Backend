"""
DiscoveryService — orchestrates all search flows.

Responsibilities
----------------
1. Text Search flow
   - Resolve user location from DB (optional soft bias)
   - Build a Redis cache key
   - Check Redis; on hit return immediately
   - On miss: call GoogleTextSearchClient
   - Write result to Redis
   - Persist audit rows to PostgreSQL (search_queries + search_results)
   - Return (places, from_cache, lat, lon)

2. Nearby Search flow
   - Resolve user location from DB (required — raises 404 if absent)
   - Build a Redis cache key (re-uses nearby: prefix for consistency)
   - Check Redis; on hit return immediately
   - On miss: call GooglePlacesClient (the existing nearby client)
   - Write result to Redis
   - Persist audit rows to PostgreSQL
   - Return (places, from_cache, lat, lon)

3. Discovery Router flow
   - Inspect the incoming query string
   - Apply routing rules (see _choose_mode docstring)
   - Delegate to text or nearby path
   - Attach resolved_mode to the audit row

Design rules
------------
- Service never raises HTTP exceptions that are not already raised by
  the integration clients.  Business logic 404 (no saved location) is
  delegated to UserLocationNotFoundError (already in exceptions/places.py).
- DB commit is done here (not in the repository) so the whole
  search + audit write is one atomic transaction.
- Redis failures are logged but never crash the request (cache is advisory).
"""

import hashlib
import json
import logging
import re
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.exceptions.places import UserLocationNotFoundError
from app.integrations.google_places import GooglePlacesClient
from app.integrations.google_text_search import GoogleTextSearchClient
from app.models.user_location import UserLocation
from app.repositories.redis_repository import RedisRepository
from app.repositories.search_repository import SearchRepository
from app.schemas.discovery import (
    DiscoveryPlaceResult,
    DiscoverySearchRequest,
    NearbyDiscoveryRequest,
    TextSearchRequest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing heuristics — keywords that signal "geo-first / nearby" intent.
# If ANY token in the query matches, we route to Nearby Search.
# ---------------------------------------------------------------------------
_NEARBY_SIGNAL_PATTERN = re.compile(
    r"\b(near\s*me|around\s*me|nearby|close\s*by|closest|nearest|around\s*here"
    r"|within\s*\d+\s*(km|meters?|metres?|miles?)"
    r"|in\s+my\s+area|around\s+my\s+location)\b",
    re.IGNORECASE,
)


def _build_text_cache_key(
    user_id: int,
    text_query: str,
    bias_lat: Optional[float],
    bias_lon: Optional[float],
    max_result_count: int,
    open_now: Optional[bool],
    min_rating: Optional[float],
    rank_preference: Optional[str],
) -> str:
    """
    Deterministic Redis key for a text search request.

    We hash the full parameter set so the key stays short regardless of
    how long the query string is.  The user_id prefix prevents cross-user
    cache collision (different users may have different saved locations).

    Format: text_search:{user_id}:{sha256_hex[:16]}
    """
    lat_str = f"{round(bias_lat, 6)}" if bias_lat is not None else "none"
    lon_str = f"{round(bias_lon, 6)}" if bias_lon is not None else "none"
    raw = (
        f"{text_query.lower().strip()}|{lat_str}|{lon_str}"
        f"|{max_result_count}|{open_now}|{min_rating}|{rank_preference}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"text_search:{user_id}:{digest}"


def _build_nearby_cache_key(
    user_id: int,
    latitude: float,
    longitude: float,
    radius: float,
    max_result_count: int,
) -> str:
    """
    Nearby cache key — identical format to the existing nearby-search key
    so they share the same TTL strategy.
    """
    lat = round(latitude, 6)
    lon = round(longitude, 6)
    return f"nearby:{user_id}:{lat}:{lon}:{radius}:{max_result_count}"


class DiscoveryService:
    """
    Orchestrates text search, nearby search, and the discovery router.
    Accepts injected clients and repositories so it is fully unit-testable.
    """

    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        text_client: GoogleTextSearchClient,
        nearby_client: GooglePlacesClient,
    ) -> None:
        self.db = db
        self.redis_repo = redis_repo
        self.text_client = text_client
        self.nearby_client = nearby_client
        self.search_repo = SearchRepository(db)

    # ------------------------------------------------------------------
    # Internal: resolve user's current location from DB
    # ------------------------------------------------------------------

    def _get_user_location(self, user_id: int) -> Optional[UserLocation]:
        """
        Fetch the active current location for a user.
        Returns None (not raises) so callers can decide whether it is required.
        """
        return (
            self.db.query(UserLocation)
            .filter(
                UserLocation.user_id == user_id,
                UserLocation.is_current.is_(True),
                UserLocation.is_active.is_(True),
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Internal: cache helpers
    # ------------------------------------------------------------------

    async def _try_get_cache(
        self, key: str
    ) -> Optional[List[DiscoveryPlaceResult]]:
        """Return cached places or None.  Never raises."""
        cached = await self.redis_repo.get(key)
        if cached is not None:
            try:
                return [DiscoveryPlaceResult(**item) for item in cached]
            except Exception as exc:
                logger.warning("Cache deserialisation failed for key %s: %s", key, exc)
        return None

    async def _try_set_cache(
        self, key: str, places: List[DiscoveryPlaceResult], ttl: Optional[int] = None
    ) -> None:
        """Persist places to Redis.  Never raises."""
        try:
            serialisable = [p.model_dump() for p in places]
            await self.redis_repo.set(key, serialisable, ttl=ttl)
        except Exception as exc:
            logger.warning("Cache write failed for key %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Internal: audit persistence
    # ------------------------------------------------------------------

    def _persist_audit(
        self,
        *,
        user_id: int,
        search_mode: str,
        resolved_mode: Optional[str],
        raw_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        radius: Optional[float],
        places: List[DiscoveryPlaceResult],
        from_cache: bool,
    ) -> None:
        """
        Write search_query + search_results rows inside one transaction.
        Commit is called here.  On any DB error, log and swallow — a failed
        audit write must never break the user-facing response.
        """
        try:
            query_row = self.search_repo.create_search_query(
                user_id=user_id,
                search_mode=search_mode,
                resolved_mode=resolved_mode,
                raw_query=raw_query,
                latitude=latitude,
                longitude=longitude,
                radius=radius,
                result_count=len(places),
                from_cache=from_cache,
            )
            self.search_repo.create_search_results(
                query_id=query_row.id,
                user_id=user_id,
                places=places,
            )
            self.db.commit()
        except Exception as exc:
            logger.error(
                "Audit persist failed (user=%s mode=%s query=%r): %s",
                user_id, search_mode, raw_query, exc,
            )
            self.db.rollback()

    # ------------------------------------------------------------------
    # 1. Text Search
    # ------------------------------------------------------------------

    async def text_search(
        self,
        request: TextSearchRequest,
        user_id: int,
    ) -> Tuple[List[DiscoveryPlaceResult], bool, Optional[float], Optional[float]]:
        """
        Execute a text search and return (places, from_cache, lat, lon).

        Location bias logic (priority order):
          1. Explicit location_bias in the request payload.
          2. User's saved location (when use_user_location_as_bias=True).
          3. No bias → Google uses IP-based biasing.
        """
        # Resolve bias coordinates
        bias_lat: Optional[float] = None
        bias_lon: Optional[float] = None
        bias_radius: Optional[float] = None

        if request.location_bias:
            bias_lat = request.location_bias.latitude
            bias_lon = request.location_bias.longitude
            bias_radius = request.location_bias.radius
            logger.debug(
                "Text Search bias: explicit payload (%s, %s) r=%s",
                bias_lat, bias_lon, bias_radius,
            )
        elif request.use_user_location_as_bias:
            loc = self._get_user_location(user_id)
            if loc:
                bias_lat = loc.latitude
                bias_lon = loc.longitude
                bias_radius = 5000.0   # default bias radius when auto-injected
                logger.debug(
                    "Text Search bias: user saved location (%s, %s)",
                    bias_lat, bias_lon,
                )
            else:
                logger.info(
                    "Text Search for user %s: no saved location, Google uses IP bias",
                    user_id,
                )

        # Build cache key
        cache_key = _build_text_cache_key(
            user_id=user_id,
            text_query=request.text_query,
            bias_lat=bias_lat,
            bias_lon=bias_lon,
            max_result_count=request.max_result_count,
            open_now=request.open_now,
            min_rating=request.min_rating,
            rank_preference=(
                request.rank_preference.value if request.rank_preference else None
            ),
        )

        # Redis check
        cached_places = await self._try_get_cache(cache_key)
        if cached_places is not None:
            logger.info(
                "Text Search cache HIT — user=%s query=%r", user_id, request.text_query
            )
            self._persist_audit(
                user_id=user_id,
                search_mode="text",
                resolved_mode="text",
                raw_query=request.text_query,
                latitude=bias_lat,
                longitude=bias_lon,
                radius=bias_radius,
                places=cached_places,
                from_cache=True,
            )
            return cached_places, True, bias_lat, bias_lon

        # Cache miss → call Google
        logger.info(
            "Text Search cache MISS — user=%s query=%r → calling Google",
            user_id, request.text_query,
        )
        places = await self.text_client.search_text(
            text_query=request.text_query,
            max_result_count=request.max_result_count,
            open_now=request.open_now,
            min_rating=request.min_rating,
            rank_preference=(
                request.rank_preference.value if request.rank_preference else None
            ),
            location_bias_lat=bias_lat,
            location_bias_lon=bias_lon,
            location_bias_radius=bias_radius,
        )

        # Write to cache
        await self._try_set_cache(cache_key, places)

        # Audit
        self._persist_audit(
            user_id=user_id,
            search_mode="text",
            resolved_mode="text",
            raw_query=request.text_query,
            latitude=bias_lat,
            longitude=bias_lon,
            radius=bias_radius,
            places=places,
            from_cache=False,
        )

        return places, False, bias_lat, bias_lon

    # ------------------------------------------------------------------
    # 2. Nearby Search
    # ------------------------------------------------------------------

    async def nearby_search(
        self,
        request: NearbyDiscoveryRequest,
        user_id: int,
    ) -> Tuple[List[DiscoveryPlaceResult], bool, float, float]:
        """
        Execute a geo-bounded nearby search.
        Raises UserLocationNotFoundError if user has no saved location.
        Returns (places, from_cache, lat, lon).
        """
        # Location is mandatory for nearby search
        loc = self._get_user_location(user_id)
        if loc is None:
            logger.warning(
                "Nearby search blocked — user_id %s has no saved location", user_id
            )
            raise UserLocationNotFoundError()

        latitude = loc.latitude
        longitude = loc.longitude

        cache_key = _build_nearby_cache_key(
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            max_result_count=request.max_result_count,
        )

        # Redis check
        cached_places = await self._try_get_cache(cache_key)
        if cached_places is not None:
            logger.info(
                "Nearby Discovery cache HIT — user=%s lat=%s lon=%s",
                user_id, latitude, longitude,
            )
            self._persist_audit(
                user_id=user_id,
                search_mode="nearby",
                resolved_mode="nearby",
                raw_query=None,
                latitude=latitude,
                longitude=longitude,
                radius=request.radius,
                places=cached_places,
                from_cache=True,
            )
            return cached_places, True, latitude, longitude

        # Cache miss → call Google Nearby Search
        logger.info(
            "Nearby Discovery cache MISS — user=%s → calling Google", user_id
        )

        # GooglePlacesClient returns List[PlaceResult] (existing schema).
        # We convert to DiscoveryPlaceResult for a unified type contract.
        raw_places = await self.nearby_client.search_nearby(
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            max_result_count=request.max_result_count,
        )

        places: List[DiscoveryPlaceResult] = [
            DiscoveryPlaceResult(
                place_id=p.place_id,
                display_name=p.display_name,
                formatted_address=p.formatted_address,
                latitude=p.latitude,
                longitude=p.longitude,
                rating=p.rating,
                user_rating_count=p.user_rating_count,
                primary_type=p.primary_type,
                business_status=p.business_status,
                google_maps_uri=p.google_maps_uri,
            )
            for p in raw_places
        ]

        await self._try_set_cache(cache_key, places)

        self._persist_audit(
            user_id=user_id,
            search_mode="nearby",
            resolved_mode="nearby",
            raw_query=None,
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            places=places,
            from_cache=False,
        )

        return places, False, latitude, longitude

    # ------------------------------------------------------------------
    # 3. Discovery Router
    # ------------------------------------------------------------------

    def _choose_mode(self, query: Optional[str]) -> str:
        """
        Determine search mode from the user's query string.

        Rules (applied in order):
          1. No query → "nearby"  (pure location browse)
          2. Query matches geo-signal pattern → "nearby"
          3. Query is free-text → "text"
        """
        if not query or not query.strip():
            return "nearby"
        if _NEARBY_SIGNAL_PATTERN.search(query):
            return "nearby"
        return "text"

    async def discovery_search(
        self,
        request: DiscoverySearchRequest,
        user_id: int,
    ) -> Tuple[List[DiscoveryPlaceResult], bool, str, Optional[float], Optional[float]]:
        """
        Unified entry point for the frontend.

        Returns (places, from_cache, resolved_mode, lat, lon).
        `resolved_mode` tells the caller which path actually ran.
        """
        mode = self._choose_mode(request.query)
        logger.info(
            "Discovery Router — user=%s query=%r → mode=%s",
            user_id, request.query, mode,
        )

        if mode == "text":
            text_req = TextSearchRequest(
                text_query=request.query,  # type: ignore[arg-type]
                max_result_count=request.max_result_count,
                open_now=request.open_now,
                min_rating=request.min_rating,
                rank_preference=request.rank_preference,
                use_user_location_as_bias=True,
            )
            places, from_cache, lat, lon = await self.text_search(text_req, user_id)
            return places, from_cache, "text", lat, lon

        else:  # nearby
            nearby_req = NearbyDiscoveryRequest(
                radius=request.radius,
                max_result_count=request.max_result_count,
            )
            places, from_cache, lat, lon = await self.nearby_search(nearby_req, user_id)
            return places, from_cache, "nearby", lat, lon
