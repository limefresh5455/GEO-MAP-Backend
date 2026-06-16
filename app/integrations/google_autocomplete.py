"""
Google Places Autocomplete (New) client — Phase 2 / Autocomplete Feature.

Returns place predictions as the user types their search query.

How the Google Places Autocomplete API works
---------------------------------------------
The Autocomplete (New) API accepts an input string (e.g. "bur") and
returns a list of place predictions with:
  - place_id         : stable identifier for the place
  - structured_format: main text + secondary text for two-line display
  - types            : place type categories (e.g. ["restaurant", "food"])

The API call format:
    POST https://places.googleapis.com/v1/places:autocomplete
    Headers: X-Goog-Api-Key, X-Goog-FieldMask
    Body: { "input": "bur", "locationBias": {...}, ... }

Strategy used here
------------------
- We use locationBias (circle) to prioritize suggestions near the user.
- Results are cached in Redis for 5 minutes (autocomplete results change
  frequently as businesses open/close, so shorter TTL than place details).
- The frontend should debounce input and only call once the user has
  typed at least 2 characters to reduce API calls.
- Predictions are returned as-is; the frontend calls the Places Details
  API when the user selects a suggestion to get full place data.

Architecture notes
------------------
- Shares the same httpx.AsyncClient pattern as all other Google clients
  (B10 pattern — connection pool injected from app.state).
- Raises the same exception hierarchy (GooglePlacesAPIError etc.) so the
  service layer has one consistent error surface.
- input_offset is not implemented (it is used for highlighting matched
  text in the UI, but the frontend can do this client-side).
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

logger = logging.getLogger(__name__)


class GoogleAutocompleteClient:
    """
    Async client for the Google Places Autocomplete (New) API.

    Returns place predictions as the user types their search query.

    Parameters
    ----------
    http_client : httpx.AsyncClient, optional
        Shared connection-pooled client from app.state (B10 pattern).
        When None, a per-call client is created (test/fallback mode).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self._http_client = http_client
        # Autocomplete should be fast — slightly shorter timeout than other APIs
        self._timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request_body(
        self,
        input_text: str,
        location_bias_lat: Optional[float],
        location_bias_lon: Optional[float],
        location_bias_radius: Optional[float],
        included_primary_types: Optional[List[str]],
        language_code: Optional[str],
    ) -> Dict[str, Any]:
        """
        Build the JSON request body for the Autocomplete API.

        Google requires:
          - input: the text fragment (minimum 1 char, but we enforce 2+ at service layer)
          - locationBias (optional): circle around user's location
          - includedPrimaryTypes (optional): filter by place categories
          - languageCode (optional): preferred language for results (default "en")
        """
        body: Dict[str, Any] = {
            "input": input_text,
        }

        # Location bias — prioritize results near this coordinate
        if (
            location_bias_lat is not None
            and location_bias_lon is not None
            and location_bias_radius is not None
        ):
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": location_bias_lat,
                        "longitude": location_bias_lon,
                    },
                    "radius": location_bias_radius,
                }
            }

        # Type filters — restrict to specific place types (e.g. ["restaurant", "cafe"])
        if included_primary_types:
            body["includedPrimaryTypes"] = included_primary_types

        # Language preference (default to English)
        body["languageCode"] = language_code or "en"

        return body

    def _parse_predictions(self, raw_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse the Google Autocomplete response into a clean list of predictions.

        Each prediction contains:
          - place_id           : stable identifier
          - main_text          : primary display text (e.g. "Burj Khalifa")
          - secondary_text     : secondary display text (e.g. "Dubai, UAE")
          - types              : list of place type tags (e.g. ["tourist_attraction"])
          - full_text          : complete description (main + secondary)

        Returns an empty list if no predictions are found.
        """
        suggestions = raw_response.get("suggestions", [])
        predictions = []

        for suggestion in suggestions:
            place_prediction = suggestion.get("placePrediction")
            if not place_prediction:
                continue  # skip non-place suggestions (e.g. query suggestions)

            # Extract structured format for two-line display
            structured = place_prediction.get("structuredFormat", {})
            main_text = structured.get("mainText", {}).get("text", "")
            secondary_text = structured.get("secondaryText", {}).get("text", "")

            predictions.append({
                "place_id": place_prediction.get("placeId", ""),
                "main_text": main_text,
                "secondary_text": secondary_text,
                "full_text": place_prediction.get("text", {}).get("text", ""),
                "types": place_prediction.get("types", []),
            })

        return predictions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def autocomplete(
        self,
        input_text: str,
        location_bias_lat: Optional[float] = None,
        location_bias_lon: Optional[float] = None,
        location_bias_radius: Optional[float] = 5000.0,
        included_primary_types: Optional[List[str]] = None,
        language_code: str = "en",
    ) -> List[Dict[str, Any]]:
        """
        Get place autocomplete predictions for the given input text.

        Parameters
        ----------
        input_text              : partial search query (e.g. "bur")
        location_bias_lat       : latitude for location bias (optional)
        location_bias_lon       : longitude for location bias (optional)
        location_bias_radius    : bias radius in meters (default 5000 = 5km)
        included_primary_types  : filter by place types (e.g. ["restaurant"])
        language_code           : preferred language (default "en")

        Returns
        -------
        List of prediction dicts, each containing:
          - place_id: stable identifier for the place
          - main_text: primary display text (e.g. "Burj Khalifa")
          - secondary_text: secondary display text (e.g. "Dubai, UAE")
          - full_text: complete description
          - types: list of place type tags

        Raises
        ------
        GooglePlacesRateLimitError : if Google returns 429
        GooglePlacesAPIError       : on 400 (bad request) or 403 (auth failure)
        GooglePlacesTimeoutError   : if request times out
        """
        url = f"{self.base_url}/places:autocomplete"
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

        body = self._build_request_body(
            input_text=input_text,
            location_bias_lat=location_bias_lat,
            location_bias_lon=location_bias_lon,
            location_bias_radius=location_bias_radius,
            included_primary_types=included_primary_types,
            language_code=language_code,
        )

        async def _call(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
            try:
                response = await client.post(url, headers=headers, json=body)

                # Handle error status codes
                if response.status_code == 429:
                    raise GooglePlacesRateLimitError(
                        "Places Autocomplete API rate limit exceeded (429)"
                    )

                if response.status_code == 403:
                    raise GooglePlacesAPIError(
                        "Places Autocomplete API: 403 Forbidden — check API key billing."
                    )

                if response.status_code == 400:
                    error_detail = response.text[:200]
                    raise GooglePlacesAPIError(
                        f"Places Autocomplete API: 400 Bad Request — {error_detail}"
                    )

                if response.status_code != 200:
                    raise GooglePlacesAPIError(
                        f"Places Autocomplete API returned status {response.status_code}"
                    )

                data = response.json()
                predictions = self._parse_predictions(data)

                logger.info(
                    "Autocomplete complete — input: %r, predictions: %d",
                    input_text,
                    len(predictions),
                )
                return predictions

            except (GooglePlacesRateLimitError, GooglePlacesAPIError):
                raise
            except httpx.TimeoutException as exc:
                raise GooglePlacesTimeoutError(
                    f"Places Autocomplete request timed out: {exc}"
                ) from exc
            except Exception as exc:
                raise GooglePlacesAPIError(
                    f"Places Autocomplete client error: {exc}"
                ) from exc

        # Execute with shared or per-call client
        if self._http_client:
            return await _call(self._http_client)
        else:
            logger.warning(
                "GoogleAutocompleteClient: no shared client — "
                "creating per-call client (should only happen in tests)"
            )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await _call(client)
