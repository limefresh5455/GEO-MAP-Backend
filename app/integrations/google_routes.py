"""
Google Routes API client.

Provides two operations that map directly to the Routes API v2:

  1. compute_route()        — single origin → destination route
     Endpoint: POST /directions/v2:computeRoutes
     Use case: "Get directions to this place" — returns distance, duration,
               encoded polyline, and turn-by-turn navigation steps.

  2. compute_route_matrix() — one origin → N destinations (batch ETA)
     Endpoint: POST /directions/v2:computeRouteMatrix
     Use case: Enrich discovery result cards with live driving ETAs without
               making N sequential API calls.

Architecture notes
------------------
- Follows the same shared-httpx-client pattern as GooglePlacesClient (B10).
  A connection-pooled AsyncClient is injected at construction time from
  app.state; falls back to a per-call client for tests.
- Field masks are explicit and minimal to reduce latency and billing cost.
- Raises the same exception hierarchy as the Places clients so the service
  layer can catch a single exception type.
- Routes API base URL is separate from Places API — different host entirely
  (routes.googleapis.com vs places.googleapis.com).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
)
from app.schemas.routes import (
    RouteMatrixElement,
    RouteResult,
    TravelMode,
    RoutingPreference,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field masks — only request what we display/store to minimise cost & latency.
# Google bills based on which fields are requested; using * in production is
# explicitly discouraged in the official documentation.
# ---------------------------------------------------------------------------

# Single-route field mask:
#   routes.distanceMeters  — total distance
#   routes.duration        — total travel time (e.g. "1200s")
#   routes.staticDuration  — duration without live traffic
#   routes.polyline        — encoded route shape for map rendering
#   routes.legs            — per-leg distance/duration for multi-stop trips
#   routes.legs.steps      — turn-by-turn navigation steps
#   routes.optimizedIntermediateWaypointIndex — Phase 6: reordered waypoint indices
COMPUTE_ROUTE_FIELD_MASK = ",".join([
    "routes.distanceMeters",
    "routes.duration",
    "routes.staticDuration",
    "routes.polyline.encodedPolyline",
    "routes.legs.distanceMeters",
    "routes.legs.duration",
    "routes.legs.steps.distanceMeters",
    "routes.legs.steps.staticDuration",
    "routes.legs.steps.navigationInstruction",
    "routes.optimizedIntermediateWaypointIndex",
])

# Route matrix field mask:
#   originIndex / destinationIndex — which pair this element represents
#   distanceMeters / duration      — the key values we surface in the UI
#   status                         — per-element errors (some pairs may fail)
ROUTE_MATRIX_FIELD_MASK = ",".join([
    "originIndex",
    "destinationIndex",
    "distanceMeters",
    "duration",
    "status",
    "condition",
])


class GoogleRoutesClient:
    """
    Async wrapper around the Google Routes API v2.

    Parameters
    ----------
    http_client : httpx.AsyncClient, optional
        Shared connection-pooled client injected from app.state (B10 pattern).
        When None, a new client is created per call (test / fallback mode).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY  # same key, different service
        self.base_url = settings.GOOGLE_ROUTES_BASE_URL
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self, field_mask: str) -> Dict[str, str]:
        """
        Build the standard Google Routes API request headers.

        The Routes API uses the same auth mechanism as Places API:
          - X-Goog-Api-Key  — API key authentication
          - X-Goog-FieldMask — explicit field selection (required; no default)
        """
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }

    def _build_waypoint(
        self,
        latitude: float,
        longitude: float,
        place_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a Routes API waypoint object.

        When a place_id is available (origin is a discovered place) we use
        it directly — Google can resolve it without a geocoding round-trip,
        which is faster and cheaper than sending raw coordinates for a place
        that was already found via Places API.

        For the user's current location we always use raw coordinates because
        UserLocation records do not have a place_id.
        """
        if place_id:
            return {"placeId": place_id}
        return {
            "location": {
                "latLng": {
                    "latitude": latitude,
                    "longitude": longitude,
                }
            }
        }

    async def _post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        field_mask: str,
    ) -> Dict[str, Any]:
        """
        POST to a Routes API endpoint and return the parsed JSON response.

        Handles:
          - 200 OK              → return parsed body
          - 429 Too Many Requests → GooglePlacesRateLimitError
          - 400/403/404         → GooglePlacesAPIError (with details)
          - Timeout             → GooglePlacesTimeoutError
        """
        url = f"{self.base_url}:{endpoint}"
        headers = self._build_headers(field_mask)

        async def _do_request(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(url, json=payload, headers=headers)

        try:
            if self._http_client:
                response = await _do_request(self._http_client)
            else:
                logger.warning(
                    "GoogleRoutesClient: no shared client injected — "
                    "creating a per-call client (should only happen in tests)"
                )
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await _do_request(client)

        except httpx.TimeoutException as exc:
            raise GooglePlacesTimeoutError(
                f"Routes API request timed out: {exc}"
            ) from exc

        if response.status_code == 429:
            raise GooglePlacesRateLimitError("Routes API rate limit exceeded (429)")

        if response.status_code != 200:
            raise GooglePlacesAPIError(
                f"Routes API error {response.status_code}: {response.text[:300]}"
            )

        return response.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compute_route(
        self,
        origin_lat: float,
        origin_lon: float,
        destination_lat: float,
        destination_lon: float,
        destination_place_id: Optional[str] = None,
        waypoints: Optional[List[Dict[str, Any]]] = None,
        optimize_waypoint_order: bool = False,
        departure_time: Optional[datetime] = None,
        travel_mode: TravelMode = TravelMode.DRIVE,
        routing_preference: RoutingPreference = RoutingPreference.TRAFFIC_AWARE,
        language_code: str = "en-US",
        avoid_tolls: bool = False,
        avoid_highways: bool = False,
        avoid_ferries: bool = False,
    ) -> RouteResult:
        """
        Compute a single route from origin to destination.

        Parameters
        ----------
        origin_lat / origin_lon     : user's current GPS location
        destination_lat / lon       : place coordinates from PlaceDetail
        destination_place_id        : optional Google place_id — preferred
                                      when available (skips internal geocoding)
        waypoints                   : list of intermediate stops (Phase 6)
                                      Each should have 'place_id' or 'lat'+'lon'
        optimize_waypoint_order     : if True, Google reorders waypoints
                                      to minimize total travel time (Phase 6)
        departure_time              : optional datetime for planned departure (Phase 7)
                                      Used to predict traffic at that time
        travel_mode                 : DRIVE | WALK (TWO_WHEELER / BICYCLE available)
        routing_preference          : TRAFFIC_AWARE (default) | TRAFFIC_AWARE_OPTIMAL
                                      | TRAFFIC_UNAWARE (for WALK, must use UNAWARE)
        language_code               : BCP-47 language tag for navigation text
        avoid_tolls / highways / ferries : route modifier flags

        Returns
        -------
        RouteResult with distance_meters, duration_seconds, encoded_polyline,
        and structured navigation steps. If waypoints were optimized, includes
        optimized_waypoint_order list showing the reordered indices.

        Raises
        ------
        GooglePlacesAPIError        : on non-200, non-429 errors
        GooglePlacesRateLimitError  : on 429
        GooglePlacesTimeoutError    : on network timeout
        """
        # WALK mode does not support traffic-aware routing — Google returns an
        # error if you combine WALK with TRAFFIC_AWARE. Override automatically.
        effective_routing_preference = routing_preference
        if travel_mode == TravelMode.WALK:
            effective_routing_preference = RoutingPreference.TRAFFIC_UNAWARE

        payload: Dict[str, Any] = {
            "origin": self._build_waypoint(origin_lat, origin_lon),
            "destination": self._build_waypoint(
                destination_lat,
                destination_lon,
                place_id=destination_place_id,
            ),
            "travelMode": travel_mode.value,
            "routingPreference": effective_routing_preference.value,
            "computeAlternativeRoutes": False,  # keep costs down; enable later if needed
            "languageCode": language_code,
            "units": "METRIC",
            "routeModifiers": {
                "avoidTolls": avoid_tolls,
                "avoidHighways": avoid_highways,
                "avoidFerries": avoid_ferries,
            },
        }

        # Phase 6: Add waypoints if provided
        if waypoints:
            intermediates = []
            for wp in waypoints:
                waypoint_obj = self._build_waypoint(
                    wp.get("lat", 0.0),
                    wp.get("lon", 0.0),
                    place_id=wp.get("place_id"),
                )
                intermediates.append({"waypoint": waypoint_obj})
            
            payload["intermediates"] = intermediates
            payload["optimizeWaypointOrder"] = optimize_waypoint_order

        # Phase 7: Add departure time if provided
        if departure_time:
            # Google expects RFC3339 format: "2024-01-15T14:30:00Z"
            payload["departureTime"] = departure_time.isoformat()

        logger.info(
            "Routes API computeRoutes — mode: %s, origin: (%.4f, %.4f), "
            "destination: %s, waypoints: %d, departure_time: %s",
            travel_mode.value,
            origin_lat,
            origin_lon,
            destination_place_id or f"({destination_lat:.4f}, {destination_lon:.4f})",
            len(waypoints) if waypoints else 0,
            departure_time.isoformat() if departure_time else "now",
        )

        data = await self._post("computeRoutes", payload, COMPUTE_ROUTE_FIELD_MASK)
        return self._parse_route_response(data)

    async def compute_route_matrix(
        self,
        origin_lat: float,
        origin_lon: float,
        destinations: List[Dict[str, Any]],
        travel_mode: TravelMode = TravelMode.DRIVE,
        routing_preference: RoutingPreference = RoutingPreference.TRAFFIC_AWARE,
    ) -> List[RouteMatrixElement]:
        """
        Compute travel times and distances from one origin to multiple destinations.

        Used to enrich discovery search results with live ETAs without making
        N sequential computeRoutes calls.  The Route Matrix API handles up to
        625 elements (origins × destinations); with one origin that means up to
        625 destinations per call. We cap at 20 to match the discovery limit.

        Parameters
        ----------
        origin_lat / origin_lon : user's current GPS location
        destinations            : list of {"place_id": ..., "lat": ..., "lon": ...}
                                  dicts built from DiscoveryPlaceResult items

        Returns
        -------
        List[RouteMatrixElement] sorted by destination index.
        Some elements may have a non-OK status (unreachable destination);
        callers should handle those gracefully.

        Raises
        ------
        Same exception hierarchy as compute_route().
        """
        if not destinations:
            return []

        if travel_mode == TravelMode.WALK:
            routing_preference = RoutingPreference.TRAFFIC_UNAWARE

        # Build a single origin
        origins = [
            {
                "waypoint": self._build_waypoint(origin_lat, origin_lon),
            }
        ]

        # Build destination waypoints — prefer place_id when available
        dest_waypoints = []
        for dest in destinations:
            waypoint = self._build_waypoint(
                dest["lat"],
                dest["lon"],
                place_id=dest.get("place_id"),
            )
            dest_waypoints.append({"waypoint": waypoint})

        payload: Dict[str, Any] = {
            "origins": origins,
            "destinations": dest_waypoints,
            "travelMode": travel_mode.value,
            "routingPreference": routing_preference.value,
        }

        logger.info(
            "Routes API computeRouteMatrix — mode: %s, origin: (%.4f, %.4f), "
            "destinations: %d",
            travel_mode.value,
            origin_lat,
            origin_lon,
            len(destinations),
        )

        data = await self._post(
            "computeRouteMatrix", payload, ROUTE_MATRIX_FIELD_MASK
        )
        return self._parse_matrix_response(data)

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    def _parse_route_response(self, data: Dict[str, Any]) -> RouteResult:
        """
        Parse a computeRoutes JSON response into a RouteResult schema object.

        Google always returns a "routes" array; we take the first element
        (best route). If the array is empty Google found no route — we raise
        an APIError so the service layer can return a clean 404.
        """
        routes = data.get("routes", [])
        if not routes:
            raise GooglePlacesAPIError(
                "Routes API returned no route for the given origin/destination. "
                "The destination may be unreachable by the selected travel mode."
            )

        route = routes[0]

        # Parse turn-by-turn steps from the first (and only) leg
        steps = []
        legs = route.get("legs", [])
        if legs:
            for step in legs[0].get("steps", []):
                nav = step.get("navigationInstruction", {})
                steps.append({
                    "distance_meters": step.get("distanceMeters", 0),
                    "duration_seconds": _duration_to_seconds(
                        step.get("staticDuration", "0s")
                    ),
                    "maneuver": nav.get("maneuver", ""),
                    "instruction": nav.get("instructions", ""),
                })

        # Extract base metrics
        distance_meters = route.get("distanceMeters", 0)
        duration_seconds = _duration_to_seconds(route.get("duration", "0s"))
        static_duration_seconds = _duration_to_seconds(
            route.get("staticDuration", "0s")
        )

        # Compute traffic delay (Phase 5)
        traffic_delay_seconds = max(0, duration_seconds - static_duration_seconds)

        # Format human-readable text (Phase 5)
        distance_text = _format_distance(distance_meters)
        duration_text = _format_duration(duration_seconds)
        traffic_delay_text = (
            _format_duration(traffic_delay_seconds) + " delay"
            if traffic_delay_seconds > 0
            else None
        )

        # Extract optimized waypoint order (Phase 6)
        optimized_order = route.get("optimizedIntermediateWaypointIndex")

        return RouteResult(
            distance_meters=distance_meters,
            duration_seconds=duration_seconds,
            static_duration_seconds=static_duration_seconds,
            traffic_delay_seconds=traffic_delay_seconds,
            distance_text=distance_text,
            duration_text=duration_text,
            traffic_delay_text=traffic_delay_text,
            encoded_polyline=route.get("polyline", {}).get("encodedPolyline", ""),
            steps=steps,
            optimized_waypoint_order=optimized_order,
        )

    def _parse_matrix_response(
        self, data: Any
    ) -> List[RouteMatrixElement]:
        """
        Parse a computeRouteMatrix streaming JSON response.

        The Route Matrix API returns a JSON array (not an object with a
        wrapper key), unlike computeRoutes.  Each element has originIndex,
        destinationIndex, distanceMeters, duration, and status.
        """
        if not isinstance(data, list):
            # Some error responses come back as an object with an "error" key
            error_msg = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else str(data)
            raise GooglePlacesAPIError(
                f"Route Matrix API returned unexpected response: {error_msg}"
            )

        elements = []
        for item in data:
            # Skip elements with non-OK status (destination unreachable, etc.)
            condition = item.get("condition", "ROUTE_EXISTS")
            status_code = item.get("status", {}).get("code", 0)
            is_ok = condition == "ROUTE_EXISTS" and status_code == 0

            elements.append(RouteMatrixElement(
                origin_index=item.get("originIndex", 0),
                destination_index=item.get("destinationIndex", 0),
                distance_meters=item.get("distanceMeters") if is_ok else None,
                duration_seconds=(
                    _duration_to_seconds(item.get("duration", "0s"))
                    if is_ok else None
                ),
                condition=condition,
            ))

        return sorted(elements, key=lambda e: e.destination_index)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _duration_to_seconds(duration_str: str) -> int:
    """
    Convert a Google duration string like "1200s" to an integer (1200).

    Google Routes API always returns duration in the "Xs" (seconds) format.
    We strip the trailing "s" and parse to int. If parsing fails we return 0
    rather than crashing — a missing ETA is preferable to a 500 error.
    """
    if not duration_str:
        return 0
    try:
        return int(duration_str.rstrip("s"))
    except (ValueError, AttributeError):
        logger.warning("Failed to parse duration string: %r", duration_str)
        return 0


def _format_distance(meters: int) -> str:
    """
    Format distance in meters as human-readable text.
    
    Examples:
        250 → "250 m"
        1500 → "1.5 km"
        12345 → "12.3 km"
    """
    if meters < 1000:
        return f"{meters} m"
    km = meters / 1000.0
    return f"{km:.1f} km"


def _format_duration(seconds: int) -> str:
    """
    Format duration in seconds as human-readable text.
    
    Examples:
        45 → "1 min"
        90 → "2 min"
        3600 → "1 hr"
        3660 → "1 hr 1 min"
        7320 → "2 hr 2 min"
    """
    if seconds < 60:
        return "1 min"
    
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    
    hours = minutes // 60
    remaining_minutes = minutes % 60
    
    if remaining_minutes == 0:
        return f"{hours} hr" if hours == 1 else f"{hours} hr"
    
    return f"{hours} hr {remaining_minutes} min"
