import hashlib
import json
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
    UserLocationNotFoundError,
)
from app.integrations.google_routes import GoogleRoutesClient
from app.repositories.location_repository import LocationRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.routes import (
    ComputeRouteMatrixRequest,
    ComputeRouteRequest,
    RouteMatrixElement,
    RouteMatrixItem,
    RouteMatrixResponse,
    RouteResponse,
    RouteResult,
    TravelMode,
    RoutingPreference,
)

logger = logging.getLogger(__name__)
_ROUTE_KEY_PREFIX = "route"
_MATRIX_KEY_PREFIX = "route_matrix"


# Cache key builders
def _route_cache_key(
    user_id: int,
    travel_mode: str,
    place_id: Optional[str],
    dest_lat: Optional[float],
    dest_lon: Optional[float],
) -> str:
    if place_id:
        dest_key = place_id
    else:
        lat_str = f"{round(dest_lat, 4)}" if dest_lat else "0"
        lon_str = f"{round(dest_lon, 4)}" if dest_lon else "0"
        dest_key = hashlib.sha256(
            f"{lat_str},{lon_str}".encode()
        ).hexdigest()[:16]

    return f"{_ROUTE_KEY_PREFIX}:{user_id}:{travel_mode}:{dest_key}"


def _matrix_cache_key(
    user_id: int,
    travel_mode: str,
    destinations: list,
) -> str:
    normalised = sorted([
        (
            round(d.get("lat", 0), 4),
            round(d.get("lon", 0), 4),
            d.get("place_id", ""),
        )
        for d in destinations
    ])
    payload_hash = hashlib.sha256(
        json.dumps(normalised).encode()
    ).hexdigest()[:16]
    return f"{_MATRIX_KEY_PREFIX}:{user_id}:{travel_mode}:{payload_hash}"


# Human-readable formatting helpers
def _format_distance(meters: Optional[int]) -> Optional[str]:
    """Format distance in metres to a human-readable string."""
    if meters is None:
        return None
    if meters < 1000:
        return f"{meters} m"
    return f"{meters / 1000:.1f} km"


def _format_duration(seconds: Optional[int]) -> Optional[str]:
    """Format duration in seconds to a human-readable string."""
    if seconds is None:
        return None
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, remaining_min = divmod(minutes, 60)
    if remaining_min == 0:
        return f"{hours} h"
    return f"{hours} h {remaining_min} min"


# Service
class RoutesService:
    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        routes_client: GoogleRoutesClient,
    ) -> None:
        self._db = db
        self._redis = redis_repo
        self._client = routes_client
        self._location_repo = LocationRepository(db)

    # Single Route
    async def compute_route(
        self,
        request: ComputeRouteRequest,
        user_id: int,
    ) -> Tuple[RouteResponse, int, int]:

        # Step 1: Resolve user location from DB (required — no location → 404)
        location = self._location_repo.get_current_location(user_id)
        if not location:
            raise UserLocationNotFoundError(
                "No current location saved. POST /api/v1/locations/gps first."
            )

        origin_lat, origin_lon = location.latitude, location.longitude

        # Validate destination
        if not request.place_id and not request.has_valid_destination():
            raise GooglePlacesAPIError(
                "Either place_id or both destination_latitude and "
                "destination_longitude must be provided."
            )

        # Step 2: Check Redis cache
        cache_key = _route_cache_key(
            user_id=user_id,
            travel_mode=request.travel_mode.value,
            place_id=request.place_id,
            dest_lat=request.destination_latitude,
            dest_lon=request.destination_longitude,
        )
        cached_data = await self._redis.get(cache_key)
        if cached_data:
            try:
                result = RouteResult.model_validate_json(cached_data)
                logger.info("Route cache HIT — key: %s", cache_key)
                return (
                    RouteResponse(
                        success=True,
                        message="Route retrieved from cache",
                        cached=True,
                        travel_mode=request.travel_mode.value,
                        data=result,
                    ),
                    origin_lat,
                    origin_lon,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to deserialise cached route — treating as miss: %s", exc
                )

        # Step 3: Call Google Routes API
        logger.info(
            "Route cache MISS — calling Routes API for user_id: %s", user_id
        )
        result = await self._client.compute_route(
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=request.destination_latitude or 0.0,
            destination_lon=request.destination_longitude or 0.0,
            destination_place_id=request.place_id,
            waypoints=request.waypoints if request.waypoints else None,
            optimize_waypoint_order=request.optimize_waypoint_order,
            departure_time=request.departure_time,
            travel_mode=request.travel_mode,
            routing_preference=(
                RoutingPreference.TRAFFIC_AWARE
                if request.travel_mode == TravelMode.DRIVE
                else RoutingPreference.TRAFFIC_UNAWARE
            ),
            language_code=request.language_code,
            avoid_tolls=request.avoid_tolls,
            avoid_highways=request.avoid_highways,
            avoid_ferries=request.avoid_ferries,
        )

        # Step 4: Write to Redis
        await self._redis.set(
            cache_key,
            result.model_dump_json(),
            ttl=settings.REDIS_ROUTES_CACHE_TTL,
        )

        return (
            RouteResponse(
                success=True,
                message="Route computed successfully",
                cached=False,
                travel_mode=request.travel_mode.value,
                data=result,
            ),
            origin_lat,
            origin_lon,
        )

    # Route Matrix (batch ETAs)
    async def compute_route_matrix(
        self,
        request: ComputeRouteMatrixRequest,
        user_id: int,
    ) -> RouteMatrixResponse:
    
        # Step 1: Resolve user location
        location = self._location_repo.get_current_location(user_id)
        if not location:
            raise UserLocationNotFoundError(
                "No current location saved. POST /api/v1/locations/gps first."
            )

        origin_lat, origin_lon = location.latitude, location.longitude

        # Step 2: Cache check
        cache_key = _matrix_cache_key(
            user_id=user_id,
            travel_mode=request.travel_mode.value,
            destinations=request.destinations,
        )
        cached_data = await self._redis.get(cache_key)
        if cached_data:
            try:
                items = [
                    RouteMatrixItem.model_validate(item)
                    for item in json.loads(cached_data)
                ]
                logger.info("Route matrix cache HIT — key: %s", cache_key)
                return RouteMatrixResponse(
                    success=True,
                    message="Route matrix retrieved from cache",
                    cached=True,
                    travel_mode=request.travel_mode.value,
                    origin_latitude=origin_lat,
                    origin_longitude=origin_lon,
                    data=items,
                    total_destinations=len(items),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to deserialise cached matrix — treating as miss: %s", exc
                )

        # Step 3: Call Google Route Matrix API
        logger.info(
            "Route matrix cache MISS — calling Routes API for user_id: %s, "
            "destinations: %d",
            user_id,
            len(request.destinations),
        )
        elements: List[RouteMatrixElement] = await self._client.compute_route_matrix(
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destinations=request.destinations,
            travel_mode=request.travel_mode,
        )

        # Step 4: Merge results with input destinations (preserve order)
        items: List[RouteMatrixItem] = []
        for element in elements:
            idx = element.destination_index
            dest = request.destinations[idx] if idx < len(request.destinations) else {}

            items.append(RouteMatrixItem(
                destination_index=idx,
                place_id=dest.get("place_id"),
                distance_meters=element.distance_meters,
                duration_seconds=element.duration_seconds,
                distance_text=_format_distance(element.distance_meters),
                duration_text=_format_duration(element.duration_seconds),
                reachable=element.condition == "ROUTE_EXISTS",
            ))

        # Step 5: Write to Redis (short TTL — ETAs change with traffic)
        await self._redis.set(
            cache_key,
            json.dumps([item.model_dump() for item in items]),
            ttl=settings.REDIS_ROUTE_MATRIX_CACHE_TTL,
        )

        return RouteMatrixResponse(
            success=True,
            message="Route matrix computed successfully",
            cached=False,
            travel_mode=request.travel_mode.value,
            origin_latitude=origin_lat,
            origin_longitude=origin_lon,
            data=items,
            total_destinations=len(items),
        )
