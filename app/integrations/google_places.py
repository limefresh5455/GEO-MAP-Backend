"""
Google Places Nearby Search (New) client.

B10 FIX: Accepts a shared httpx.AsyncClient injected at construction time.
The application lifecycle (app/main.py) creates one persistent client with
connection pooling (50 max connections, 20 keepalive). This client is reused
across all requests, eliminating per-request TLS handshake overhead and
preventing OS ephemeral port exhaustion under load.

If no client is injected (e.g. in unit tests), a local per-call client is
created as a fallback — same behaviour as before the fix.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
)
from app.schemas.discovery import DiscoveryPlaceResult

logger = logging.getLogger(__name__)

# Only request the fields we actually use — reduces payload size and billing cost
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.primaryType",
    "places.googleMapsUri",
    "places.businessStatus",
])

NEARBY_SEARCH_URL = f"{settings.GOOGLE_PLACES_BASE_URL}/places:searchNearby"


class GooglePlacesClient:
    """
    Async wrapper around the Google Places Nearby Search API (New).

    Parameters
    ----------
    http_client : httpx.AsyncClient, optional
        Shared connection-pooled client injected from app.state (B10).
        When None, a new client is created per call (test/fallback mode).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

    def _build_payload(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        max_result_count: int,
        rank_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "maxResultCount": max_result_count,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": radius,
                }
            },
        }
        if rank_preference:
            payload["rankPreference"] = rank_preference
        return payload

    def _parse_place(self, raw: Dict[str, Any]) -> DiscoveryPlaceResult:
        """Map a raw Google Places API place object to DiscoveryPlaceResult."""
        location = raw.get("location", {})
        display_name = raw.get("displayName", {})
        return DiscoveryPlaceResult(
            place_id=raw.get("id"),
            display_name=(
                display_name.get("text")
                if isinstance(display_name, dict)
                else display_name
            ),
            formatted_address=raw.get("formattedAddress"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            rating=raw.get("rating"),
            user_rating_count=raw.get("userRatingCount"),
            primary_type=raw.get("primaryType"),
            business_status=raw.get("businessStatus"),
            google_maps_uri=raw.get("googleMapsUri"),
        )

    async def _do_request(self, payload: Dict, headers: Dict) -> httpx.Response:
        """
        B10: Use the injected shared client when available; fall back to a
        per-call client for tests or when called outside lifespan context.
        
        B-030 FIX: Fallback creates async client properly without blocking.
        """
        if self._http_client is not None:
            return await self._http_client.post(
                NEARBY_SEARCH_URL, json=payload, headers=headers
            )
        
        # B-030 FIX: Proper async client creation - doesn't block event loop
        logger.warning(
            "GooglePlacesClient: No shared HTTP client - creating per-request client. "
            "This should only happen in tests."
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                NEARBY_SEARCH_URL, json=payload, headers=headers
            )

    async def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        max_result_count: int,
        rank_preference: Optional[str] = None,
    ) -> List[DiscoveryPlaceResult]:
        """
        Call Google Places Nearby Search (New) and return normalised results.
        Raises mapped HTTP exceptions on failure.
        """
        payload = self._build_payload(
            latitude, longitude, radius, max_result_count, rank_preference
        )
        headers = self._build_headers()

        logger.info(
            "Google Places API call — lat: %s, lon: %s, radius: %sm, max: %s",
            latitude, longitude, radius, max_result_count,
        )

        try:
            response = await self._do_request(payload, headers)

            if response.status_code == 429:
                logger.warning("Google Places API rate limit hit")
                raise GooglePlacesRateLimitError()

            if response.status_code == 403:
                logger.error("Google Places API forbidden — check API key and billing")
                raise GooglePlacesAPIError(
                    "Google Places API authentication failed. "
                    "Verify your API key and ensure Places API (New) is enabled."
                )

            if response.status_code != 200:
                logger.error(
                    "Google Places API error %s: %s",
                    response.status_code, response.text[:500],
                )
                raise GooglePlacesAPIError(
                    f"Google Places API returned status {response.status_code}"
                )

            data = response.json()
            places_raw = data.get("places", [])
            logger.info("Google Places API returned %d results", len(places_raw))
            return [self._parse_place(p) for p in places_raw]

        except httpx.TimeoutException:
            logger.error("Google Places API request timed out")
            raise GooglePlacesTimeoutError()

        except (GooglePlacesAPIError, GooglePlacesRateLimitError, GooglePlacesTimeoutError):
            raise

        except Exception as exc:
            logger.error("Unexpected error calling Google Places API: %s", exc)
            raise GooglePlacesAPIError(str(exc))
