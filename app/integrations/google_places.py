import json
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
# Phase 4: Expanded field mask for richer search result cards
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
    "places.priceLevel",                        # Phase 4: Price range ($-$$$$)
    "places.currentOpeningHours.openNow",       # Phase 4: Currently open status
    "places.photos",                            # Phase 4: Photo thumbnails
])

NEARBY_SEARCH_URL = f"{settings.GOOGLE_PLACES_BASE_URL}/places:searchNearby"


class GooglePlacesClient:
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
        included_types: Optional[List[str]] = None,
        excluded_types: Optional[List[str]] = None,
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
            # B-031 FIX: Add language code as required by Google Places API (New)
            "languageCode": "en",
        }
        if rank_preference:
            payload["rankPreference"] = rank_preference
        
        # B-032 FIX: Ensure includedTypes is sent as a proper array, not a string
        # Google API validation fails if this is an empty list or a string
        if included_types:
            # Additional safety: ensure it's actually a list
            if isinstance(included_types, str):
                logger.error(
                    "includedTypes received as string instead of list: %s", included_types
                )
                # Try to recover by splitting
                included_types = [t.strip() for t in included_types.split(",") if t.strip()]
            
            if isinstance(included_types, list) and len(included_types) > 0:
                payload["includedTypes"] = included_types
                logger.debug("Added includedTypes to payload: %s", included_types)
            else:
                logger.warning("includedTypes invalid or empty, skipping")
        
        if excluded_types:
            if isinstance(excluded_types, list) and len(excluded_types) > 0:
                payload["excludedTypes"] = excluded_types
            else:
                logger.warning("excludedTypes invalid or empty, skipping")
        
        return payload

    def _parse_place(self, raw: Dict[str, Any]) -> DiscoveryPlaceResult:
        location = raw.get("location", {})
        display_name = raw.get("displayName", {})
        opening_hours = raw.get("currentOpeningHours", {})
        
        # Phase 4: Extract first photo for thumbnail preview
        photos_raw = raw.get("photos", [])
        first_photo_name = None
        if photos_raw and isinstance(photos_raw, list) and len(photos_raw) > 0:
            first_photo = photos_raw[0]
            if isinstance(first_photo, dict):
                first_photo_name = first_photo.get("name")
        
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
            price_level=raw.get("priceLevel"),              # Phase 4
            open_now=opening_hours.get("openNow") if opening_hours else None,  # Phase 4
            first_photo_name=first_photo_name,              # Phase 4
        )

    async def _do_request(self, payload: Dict, headers: Dict) -> httpx.Response:
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
        included_types: Optional[List[str]] = None,
        excluded_types: Optional[List[str]] = None,
    ) -> List[DiscoveryPlaceResult]:
        payload = self._build_payload(
            latitude, longitude, radius, max_result_count, rank_preference,
            included_types, excluded_types
        )
        headers = self._build_headers()

        logger.info(
            "Google Places API call — lat: %s, lon: %s, radius: %sm, max: %s, types: %s",
            latitude, longitude, radius, max_result_count,
            included_types if included_types else "all"
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
                # B-031 FIX: Enhanced error logging for debugging 400 errors
                error_body = response.text[:1000] if response.text else "No response body"
                logger.error(
                    "Google Places API error %s: %s\nRequest payload: %s",
                    response.status_code, error_body, json.dumps(payload, indent=2),
                )
                
                # Try to parse error details from response
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", {}).get("message", error_body)
                    logger.error("Google API error details: %s", error_message)
                except Exception:
                    error_message = error_body
                
                raise GooglePlacesAPIError(
                    f"Google Places API returned status {response.status_code}: {error_message}"
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
