import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.exceptions.places import UserLocationNotFoundError
from app.integrations.google_autocomplete import GoogleAutocompleteClient
from app.integrations.google_places import GooglePlacesClient
from app.integrations.google_text_search import GoogleTextSearchClient
from app.models.user_location import UserLocation
from app.repositories.redis_repository import RedisRepository
from app.repositories.search_repository import SearchRepository
from app.schemas.discovery import (
    DiscoveryPlaceResult,
    DiscoveryPreset,
    DiscoverySearchRequest,
    NearbyDiscoveryRequest,
    NearbyRankPreference,
    RankPreference,
    TextSearchRequest,
)

logger = logging.getLogger(__name__)

_NEARBY_SIGNAL_PATTERN = re.compile(
    r"\b(near\s*me|around\s*me|nearby|close\s*by|closest|nearest|around\s*here"
    r"|within\s*\d+\s*(km|meters?|metres?|miles?)"
    r"|in\s+my\s+area|around\s+my\s+location)\b",
    re.IGNORECASE,
)


def _build_text_cache_key(
    text_query: str,
    bias_lat: Optional[float],
    bias_lon: Optional[float],
    max_result_count: int,
    open_now: Optional[bool],
    min_rating: Optional[float],
    rank_preference: Optional[str],
) -> str:

    lat_str = f"{round(bias_lat, 4)}" if bias_lat is not None else "none"
    lon_str = f"{round(bias_lon, 4)}" if bias_lon is not None else "none"
    raw = (
        f"{text_query.lower().strip()}|{lat_str}|{lon_str}"
        f"|{max_result_count}|{open_now}|{min_rating}|{rank_preference}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"text_search:{digest}"


def _build_nearby_cache_key(
    latitude: float,
    longitude: float,
    radius: float,
    max_result_count: int,
) -> str:
    lat = round(latitude, 4)
    lon = round(longitude, 4)
    return f"nearby:{lat}:{lon}:{radius}:{max_result_count}"


def _build_autocomplete_cache_key(
    input_text: str,
    bias_lat: Optional[float],
    bias_lon: Optional[float],
    included_types: Optional[List[str]],
    language_code: str,
) -> str:

    lat_str = f"{round(bias_lat, 4)}" if bias_lat is not None else "none"
    lon_str = f"{round(bias_lon, 4)}" if bias_lon is not None else "none"
    types_str = ",".join(sorted(included_types)) if included_types else "none"
    raw = (
        f"{input_text.lower().strip()}|{lat_str}|{lon_str}|{types_str}|{language_code}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"autocomplete:{digest}"


class DiscoveryService:
    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        text_client: GoogleTextSearchClient,
        nearby_client: GooglePlacesClient,
        autocomplete_client: GoogleAutocompleteClient,
    ) -> None:
        self.db = db
        self.redis_repo = redis_repo
        self.text_client = text_client
        self.nearby_client = nearby_client
        self.autocomplete_client = autocomplete_client
        self.search_repo = SearchRepository(db)
        # Explicit TTL for search result caches (1 hour by default)
        from app.core.config import settings

        self._search_cache_ttl = settings.REDIS_CACHE_TTL
        self._autocomplete_cache_ttl = settings.REDIS_AUTOCOMPLETE_CACHE_TTL

    def _get_user_location(self, user_id: int) -> Optional[UserLocation]:
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

    async def _try_get_cache(self, key: str) -> Optional[List[DiscoveryPlaceResult]]:
        """Return cached places or None. Never raises. Cleans stale entries on fail."""
        cached = await self.redis_repo.get(key)
        if cached is not None:
            try:
                return [DiscoveryPlaceResult(**item) for item in cached]
            except Exception as exc:
                logger.warning(
                    "Cache deserialisation failed for key %s — deleting stale entry: %s",
                    key,
                    exc,
                )
                await self.redis_repo.delete(key)
        return None

    async def _try_set_cache(
        self, key: str, places: List[DiscoveryPlaceResult], ttl: Optional[int] = None
    ) -> None:
        """Persist places to Redis.  Never raises."""
        try:
            # Use explicit TTL if provided, otherwise use search cache TTL
            cache_ttl = ttl if ttl is not None else self._search_cache_ttl
            serialisable = [p.model_dump() for p in places]
            await self.redis_repo.set(key, serialisable, ttl=cache_ttl)
        except Exception as exc:
            logger.warning("Cache write failed for key %s: %s", key, exc)

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
        Persist audit trail using a SEPARATE database session to avoid
        rolling back the main session's committed data on failure.
        """
        try:
            from app.database.connection import SessionLocal

            audit_db = SessionLocal()
            try:
                audit_search_repo = SearchRepository(audit_db)
                query_row = audit_search_repo.create_search_query(
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
                audit_search_repo.create_search_results(
                    query_id=query_row.id,
                    user_id=user_id,
                    places=places,
                )
                audit_db.commit()
            except Exception:
                audit_db.rollback()
                raise
            finally:
                audit_db.close()
        except Exception as exc:
            logger.critical(
                "AUDIT PERSIST FAILED — search data lost (user=%s mode=%s query=%r): %s",
                user_id,
                search_mode,
                raw_query,
                exc,
                exc_info=True,
            )

    async def text_search(
        self,
        request: TextSearchRequest,
        user_id: int,
    ) -> Tuple[List[DiscoveryPlaceResult], bool, Optional[float], Optional[float]]:
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
                bias_lat,
                bias_lon,
                bias_radius,
            )
        elif request.use_user_location_as_bias:
            loc = self._get_user_location(user_id)
            if loc:
                bias_lat = loc.latitude
                bias_lon = loc.longitude
                bias_radius = 5000.0  # default bias radius when auto-injected
                logger.debug(
                    "Text Search bias: user saved location (%s, %s)",
                    bias_lat,
                    bias_lon,
                )
            else:
                logger.info(
                    "Text Search for user %s: no saved location, Google uses IP bias",
                    user_id,
                )

        # Build cache key
        cache_key = _build_text_cache_key(
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
            user_id,
            request.text_query,
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

    async def nearby_search(
        self,
        request: NearbyDiscoveryRequest,
        user_id: int,
    ) -> Tuple[List[DiscoveryPlaceResult], bool, float, float]:
        # Location is mandatory for nearby search
        loc = self._get_user_location(user_id)
        if loc is None:
            logger.warning(
                "Nearby search blocked — user_id %s has no saved location", user_id
            )
            raise UserLocationNotFoundError()

        latitude = loc.latitude
        longitude = loc.longitude

        # Handle preset and type logic
        included_types = request.included_types

        # Priority: preset > included_types > default to PREFERRED_TYPES
        if request.preset:
            included_types = self._get_preset_types(request.preset)
            logger.info(
                "Using preset '%s' for user_id %s: %s",
                request.preset.value,
                user_id,
                included_types,
            )
        elif not included_types:
            # Default to preferred types when nothing specified
            included_types = self._get_preset_types(DiscoveryPreset.PREFERRED_TYPES)
            logger.info(
                "No preset/types specified, defaulting to preferred_types for user_id %s",
                user_id,
            )
        else:
            # Custom types provided - validate format
            if isinstance(included_types, str):
                included_types = [
                    t.strip() for t in included_types.split(",") if t.strip()
                ]
                logger.warning(
                    "included_types was a string, converted to list: %s", included_types
                )
            elif not isinstance(included_types, list):
                logger.error(
                    "included_types has invalid type %s, using default",
                    type(included_types),
                )
                included_types = self._get_preset_types(DiscoveryPreset.PREFERRED_TYPES)

        cache_key = _build_nearby_cache_key(
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
                user_id,
                latitude,
                longitude,
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
        logger.info("Nearby Discovery cache MISS — user=%s → calling Google", user_id)

        places: List[DiscoveryPlaceResult] = await self.nearby_client.search_nearby(
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            max_result_count=request.max_result_count,
            rank_preference=(
                request.rank_preference.value if request.rank_preference else None
            ),
            included_types=included_types,
            excluded_types=request.excluded_types,
        )

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

    def _get_preset_types(self, preset: "DiscoveryPreset") -> List[str]:
        """
        Return place types based on discovery preset.

        - preferred_types: Everyday useful places
        - famous_places: Tourist attractions and landmarks
        """
        if preset == DiscoveryPreset.PREFERRED_TYPES:
            return [
                # Religious places
                "hindu_temple",
                "mosque",
                "church",
                # Food & Dining
                "restaurant",
                "cafe",
                # Shopping
                "shopping_mall",
                # Healthcare
                "hospital",
                "pharmacy",
                # Finance
                "bank",
                "atm",
            ]
        elif preset == DiscoveryPreset.FAMOUS_PLACES:
            return [
                # Tourist attractions
                "tourist_attraction",
                # Historical landmarks
                "historical_landmark",
                # Cultural sites
                "museum",
                "art_gallery",
                # Nature & Parks
                "park",
                "national_park",
                # Entertainment
                "amusement_park",
                "zoo",
                "aquarium",
            ]
        else:
            # Fallback to preferred types
            logger.warning("Unknown preset %s, using preferred_types", preset)
            return self._get_preset_types(DiscoveryPreset.PREFERRED_TYPES)

    # ------------------------------------------------------------------
    # 3. Discovery Router
    # ------------------------------------------------------------------

    def _choose_mode(self, query: Optional[str]) -> str:
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
        mode = self._choose_mode(request.query)
        logger.info(
            "Discovery Router — user=%s query=%r → mode=%s",
            user_id,
            request.query,
            mode,
        )

        if mode == "text":
            text_rank_preference = (
                request.rank_preference
                if isinstance(request.rank_preference, RankPreference)
                else None
            )
            text_req = TextSearchRequest(
                text_query=request.query or "",
                max_result_count=request.max_result_count,
                open_now=request.open_now,
                min_rating=request.min_rating,
                rank_preference=text_rank_preference,
                use_user_location_as_bias=True,
            )
            places, from_cache, lat, lon = await self.text_search(text_req, user_id)
            return places, from_cache, "text", lat, lon

        else:  # nearby
            nearby_rank_preference = (
                request.rank_preference
                if isinstance(request.rank_preference, NearbyRankPreference)
                else None
            )
            nearby_req = NearbyDiscoveryRequest(
                radius=request.radius,
                max_result_count=request.max_result_count,
                rank_preference=nearby_rank_preference,
            )
            places, from_cache, lat, lon = await self.nearby_search(nearby_req, user_id)
            return places, from_cache, "nearby", lat, lon

    # ------------------------------------------------------------------
    # 4. Autocomplete (Phase 2)
    # ------------------------------------------------------------------

    async def autocomplete(
        self,
        input_text: str,
        user_id: int,
        included_primary_types: Optional[List[str]] = None,
        language_code: str = "en",
        use_user_location_bias: bool = True,
    ) -> Tuple[List[Dict[str, Any]], bool, Optional[float], Optional[float]]:

        # Resolve bias coordinates
        bias_lat: Optional[float] = None
        bias_lon: Optional[float] = None
        bias_radius: Optional[float] = None

        if use_user_location_bias:
            loc = self._get_user_location(user_id)
            if loc:
                bias_lat = loc.latitude
                bias_lon = loc.longitude
                bias_radius = 5000.0  # 5km bias radius for autocomplete
                logger.debug(
                    "Autocomplete bias: user saved location (%s, %s)",
                    bias_lat,
                    bias_lon,
                )
            else:
                logger.info(
                    "Autocomplete for user %s: no saved location, Google uses IP bias",
                    user_id,
                )

        # Build cache key
        cache_key = _build_autocomplete_cache_key(
            input_text=input_text,
            bias_lat=bias_lat,
            bias_lon=bias_lon,
            included_types=included_primary_types,
            language_code=language_code,
        )

        # Redis check — cache returns raw list of dicts
        cached_predictions = await self.redis_repo.get(cache_key)
        if cached_predictions is not None:
            # Validate that cached data is a list of dicts with required keys
            if isinstance(cached_predictions, list) and all(
                isinstance(p, dict) and "place_id" in p for p in cached_predictions
            ):
                logger.info(
                    "Autocomplete cache HIT — user=%s input=%r", user_id, input_text
                )
                return cached_predictions, True, bias_lat, bias_lon
            else:
                logger.warning(
                    "Autocomplete cache stale — invalid format for key %s, deleting",
                    cache_key,
                )
                await self.redis_repo.delete(cache_key)

        # Cache miss → call Google
        logger.info(
            "Autocomplete cache MISS — user=%s input=%r → calling Google",
            user_id,
            input_text,
        )
        predictions = await self.autocomplete_client.autocomplete(
            input_text=input_text,
            location_bias_lat=bias_lat,
            location_bias_lon=bias_lon,
            location_bias_radius=bias_radius,
            included_primary_types=included_primary_types,
            language_code=language_code,
        )

        # Write to cache (shorter TTL — 5 minutes)
        try:
            await self.redis_repo.set(
                cache_key, predictions, ttl=self._autocomplete_cache_ttl
            )
        except Exception as exc:
            logger.warning(
                "Autocomplete cache write failed for key %s: %s", cache_key, exc
            )

        return predictions, False, bias_lat, bias_lon
