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

AUTOCOMPLETE_FIELD_MASK = ",".join(
    [
        "suggestions.placePrediction.placeId",
        "suggestions.placePrediction.text",
        "suggestions.placePrediction.structuredFormat",
        "suggestions.placePrediction.types",
    ]
)


class GoogleAutocompleteClient:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)

    def _build_request_body(
        self,
        input_text: str,
        location_bias_lat: Optional[float],
        location_bias_lon: Optional[float],
        location_bias_radius: Optional[float],
        included_primary_types: Optional[List[str]],
        language_code: Optional[str],
    ) -> Dict[str, Any]:
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
        suggestions = raw_response.get("suggestions", [])
        predictions = []

        for suggestion in suggestions:
            place_prediction = suggestion.get("placePrediction")
            if not place_prediction:
                continue

            structured = place_prediction.get("structuredFormat", {})
            main_text = structured.get("mainText", {}).get("text", "")
            secondary_text = structured.get("secondaryText", {}).get("text", "")

            predictions.append(
                {
                    "place_id": place_prediction.get("placeId", ""),
                    "main_text": main_text,
                    "secondary_text": secondary_text,
                    "full_text": place_prediction.get("text", {}).get("text", ""),
                    "types": place_prediction.get("types", []),
                }
            )

        return predictions

    # Public API

    async def autocomplete(
        self,
        input_text: str,
        location_bias_lat: Optional[float] = None,
        location_bias_lon: Optional[float] = None,
        location_bias_radius: Optional[float] = 5000.0,
        included_primary_types: Optional[List[str]] = None,
        language_code: str = "en",
    ) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/places:autocomplete"
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "X-Goog-FieldMask": AUTOCOMPLETE_FIELD_MASK,
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

        if self._http_client:
            return await _call(self._http_client)
        else:
            logger.warning(
                "GoogleAutocompleteClient: no shared client — "
                "creating per-call client (should only happen in tests)"
            )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await _call(client)
