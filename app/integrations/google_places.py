import logging
from typing import Any, Dict, List

import httpx

from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
)
from app.schemas.places import PlaceResult

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
    Async wrapper around the Google Places API (New).
    Handles request construction, headers, timeouts, and error mapping.
    """

    def __init__(self):
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.timeout = httpx.Timeout(
            connect=5.0, read=15.0, write=5.0, pool=5.0
        )

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
    ) -> Dict[str, Any]:
        return {
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

    def _parse_place(self, raw: Dict[str, Any]) -> PlaceResult:
        """Map a raw Google Places API place object to our PlaceResult schema."""
        location = raw.get("location", {})
        display_name = raw.get("displayName", {})

        return PlaceResult(
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

    async def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        max_result_count: int,
    ) -> List[PlaceResult]:
        """
        Call Google Places Nearby Search (New) and return normalised results.
        No category filter — all place types are returned.
        Raises mapped HTTP exceptions on failure.
        """
        payload = self._build_payload(latitude, longitude, radius, max_result_count)
        headers = self._build_headers()

        logger.info(
            "Google Places API call — lat: %s, lon: %s, radius: %sm, max: %s",
            latitude, longitude, radius, max_result_count,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    NEARBY_SEARCH_URL,
                    json=payload,
                    headers=headers,
                )

            if response.status_code == 429:
                logger.warning("Google Places API rate limit hit")
                raise GooglePlacesRateLimitError()

            if response.status_code == 403:
                logger.error(
                    "Google Places API forbidden — check API key and billing"
                )
                raise GooglePlacesAPIError(
                    "Google Places API authentication failed. "
                    "Verify your API key and ensure Places API (New) is enabled."
                )

            if response.status_code != 200:
                logger.error(
                    "Google Places API error %s: %s",
                    response.status_code,
                    response.text,
                )
                raise GooglePlacesAPIError(
                    f"Google Places API returned status {response.status_code}"
                )

            data = response.json()
            places_raw = data.get("places", [])

            logger.info(
                "Google Places API returned %d results", len(places_raw)
            )
            return [self._parse_place(p) for p in places_raw]

        except httpx.TimeoutException:
            logger.error("Google Places API request timed out")
            raise GooglePlacesTimeoutError()

        except (
            GooglePlacesAPIError,
            GooglePlacesRateLimitError,
            GooglePlacesTimeoutError,
        ):
            raise

        except Exception as exc:
            logger.error("Unexpected error calling Google Places API: %s", exc)
            raise GooglePlacesAPIError(str(exc))
