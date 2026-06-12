"""
Async wrapper around the Google Places Text Search (New) API.

Reference: https://developers.google.com/maps/documentation/places/web-service/text-search
Endpoint:  POST https://places.googleapis.com/v1/places:searchText
Auth:      X-Goog-Api-Key header
FieldMask: X-Goog-FieldMask header  ← required; omitting it returns a 400 error

Design rules
------------
- All fields fetched are declared in FIELD_MASK; add new ones here only.
- Raises mapped HTTPException subclasses so routers stay clean.
- locationBias and locationRestriction are mutually exclusive per Google's spec;
  this client only supports locationBias (soft preference). Use Nearby Search
  for hard restriction.
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

# Fields we request from Google.
# Requesting only what we display keeps payload small and controls billing tier.
# BasicData tier: id, displayName, formattedAddress, location, types, primaryType,
#                 businessStatus, googleMapsUri
# AdvancedData tier: rating, userRatingCount, currentOpeningHours
TEXT_SEARCH_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.primaryType",
    "places.types",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.currentOpeningHours.openNow",
])

TEXT_SEARCH_URL = f"{settings.GOOGLE_PLACES_BASE_URL}/places:searchText"


class GoogleTextSearchClient:
    """
    Async HTTP client for the Google Places Text Search (New) endpoint.
    One instance per request — stateless, no connection pooling needed here
    because httpx.AsyncClient is used as a context manager per call.
    """

    def __init__(self) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=15.0,
            write=5.0,
            pool=5.0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": TEXT_SEARCH_FIELD_MASK,
        }

    def _build_payload(
        self,
        text_query: str,
        max_result_count: int,
        open_now: Optional[bool],
        min_rating: Optional[float],
        rank_preference: Optional[str],
        location_bias_lat: Optional[float],
        location_bias_lon: Optional[float],
        location_bias_radius: Optional[float],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "textQuery": text_query,
            "maxResultCount": max_result_count,
        }

        if open_now is not None:
            payload["openNow"] = open_now

        if min_rating is not None:
            payload["minRating"] = min_rating

        if rank_preference:
            payload["rankPreference"] = rank_preference

        # Inject location bias when coordinates are available.
        # Google spec: locationBias and locationRestriction are mutually exclusive.
        if location_bias_lat is not None and location_bias_lon is not None:
            radius = location_bias_radius or 5000.0
            payload["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": location_bias_lat,
                        "longitude": location_bias_lon,
                    },
                    "radius": radius,
                }
            }

        return payload

    def _parse_place(self, raw: Dict[str, Any]) -> DiscoveryPlaceResult:
        """Map a raw Google place object to our normalised schema."""
        location = raw.get("location", {})
        display_name_obj = raw.get("displayName", {})
        opening_hours = raw.get("currentOpeningHours", {})

        return DiscoveryPlaceResult(
            place_id=raw.get("id"),
            display_name=(
                display_name_obj.get("text")
                if isinstance(display_name_obj, dict)
                else display_name_obj
            ),
            formatted_address=raw.get("formattedAddress"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            rating=raw.get("rating"),
            user_rating_count=raw.get("userRatingCount"),
            primary_type=raw.get("primaryType"),
            types=raw.get("types"),
            business_status=raw.get("businessStatus"),
            google_maps_uri=raw.get("googleMapsUri"),
            open_now=opening_hours.get("openNow") if opening_hours else None,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search_text(
        self,
        text_query: str,
        max_result_count: int = 20,
        open_now: Optional[bool] = None,
        min_rating: Optional[float] = None,
        rank_preference: Optional[str] = None,
        location_bias_lat: Optional[float] = None,
        location_bias_lon: Optional[float] = None,
        location_bias_radius: Optional[float] = None,
    ) -> List[DiscoveryPlaceResult]:
        """
        Call Google Text Search (New) and return normalised results.

        Parameters
        ----------
        text_query              : Human-language query string.
        max_result_count        : 1–20 (Google hard limit).
        open_now                : If True, restrict to currently open places.
        min_rating              : Minimum Google rating threshold.
        rank_preference         : "RELEVANCE" or "DISTANCE".
        location_bias_lat/lon   : Soft location hint (user's current position).
        location_bias_radius    : Bias radius in metres.

        Returns
        -------
        List[DiscoveryPlaceResult] — may be empty if Google finds nothing.

        Raises
        ------
        GooglePlacesRateLimitError  — HTTP 429
        GooglePlacesAPIError        — HTTP 403, 4xx, 5xx
        GooglePlacesTimeoutError    — network / read timeout
        """
        payload = self._build_payload(
            text_query=text_query,
            max_result_count=max_result_count,
            open_now=open_now,
            min_rating=min_rating,
            rank_preference=rank_preference,
            location_bias_lat=location_bias_lat,
            location_bias_lon=location_bias_lon,
            location_bias_radius=location_bias_radius,
        )
        headers = self._build_headers()

        logger.info(
            "Google Text Search — query: %r, max: %s, bias: (%s, %s) r=%s",
            text_query,
            max_result_count,
            location_bias_lat,
            location_bias_lon,
            location_bias_radius,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    TEXT_SEARCH_URL,
                    json=payload,
                    headers=headers,
                )

            if response.status_code == 429:
                logger.warning("Google Text Search rate limit hit")
                raise GooglePlacesRateLimitError()

            if response.status_code == 403:
                logger.error(
                    "Google Text Search forbidden — check API key and billing. "
                    "Body: %s",
                    response.text[:500],
                )
                raise GooglePlacesAPIError(
                    "Google Places API authentication failed. "
                    "Verify your API key and ensure Places API (New) is enabled."
                )

            if response.status_code != 200:
                logger.error(
                    "Google Text Search error %s: %s",
                    response.status_code,
                    response.text[:500],
                )
                raise GooglePlacesAPIError(
                    f"Google Text Search API returned status {response.status_code}"
                )

            data = response.json()
            places_raw = data.get("places", [])
            logger.info(
                "Google Text Search returned %d results for query %r",
                len(places_raw),
                text_query,
            )
            return [self._parse_place(p) for p in places_raw]

        except httpx.TimeoutException:
            logger.error(
                "Google Text Search request timed out for query %r", text_query
            )
            raise GooglePlacesTimeoutError()

        except (
            GooglePlacesAPIError,
            GooglePlacesRateLimitError,
            GooglePlacesTimeoutError,
        ):
            raise  # Already mapped — re-raise as-is

        except Exception as exc:
            logger.error(
                "Unexpected error calling Google Text Search for query %r: %s",
                text_query,
                exc,
            )
            raise GooglePlacesAPIError(str(exc))
