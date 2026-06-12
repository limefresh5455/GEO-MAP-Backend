import logging
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings
from app.exceptions.places import (
    GooglePlacesAPIError,
    GooglePlacesRateLimitError,
    GooglePlacesTimeoutError,
    PlaceDetailNotFoundError,
)
from app.schemas.place_details import (
    OpeningHours,
    OpeningHoursPeriod,
    PlaceDetailResult,
    PlacePhoto,
    PlaceReview,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field mask
# ---------------------------------------------------------------------------

DETAILS_FIELD_MASK = ",".join([
    # Identity & location
    "id",
    "displayName",
    "formattedAddress",
    "location",
    # Classification
    "types",
    "primaryType",
    # Status
    "businessStatus",
    "currentOpeningHours",
    # Contact
    "internationalPhoneNumber",
    "nationalPhoneNumber",
    "websiteUri",
    "googleMapsUri",
    # Quality signals
    "rating",
    "userRatingCount",
    "priceLevel",
    # Rich content
    "editorialSummary",
    "photos",
    "reviews",
    # Accessibility
    "accessibilityOptions",
])


class GooglePlaceDetailsClient:
    def __init__(self) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=15.0,
            write=5.0,
            pool=5.0,
        )

    # ------------------------------------------------------------------
    # Internal: header builder
    # ------------------------------------------------------------------
    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": DETAILS_FIELD_MASK,
        }

    # ------------------------------------------------------------------
    # Internal: response parsers
    # ------------------------------------------------------------------
    def _parse_opening_hours(
        self, raw: Optional[Dict[str, Any]]
    ) -> Optional[OpeningHours]:
        if not raw:
            return None

        periods: List[OpeningHoursPeriod] = []
        for period in raw.get("periods", []):
            open_p = period.get("open", {})
            close_p = period.get("close", {})
            periods.append(
                OpeningHoursPeriod(
                    open_day=open_p.get("day"),
                    open_hour=open_p.get("hour"),
                    open_minute=open_p.get("minute"),
                    close_day=close_p.get("day"),
                    close_hour=close_p.get("hour"),
                    close_minute=close_p.get("minute"),
                )
            )

        return OpeningHours(
            open_now=raw.get("openNow"),
            weekday_descriptions=raw.get("weekdayDescriptions"),
            periods=periods or None,
        )

    def _parse_photos(
        self, raw_list: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[PlacePhoto]]:
        if not raw_list:
            return None
        return [
            PlacePhoto(
                name=p.get("name"),
                width_px=p.get("widthPx"),
                height_px=p.get("heightPx"),
            )
            for p in raw_list
        ]

    def _parse_reviews(
        self, raw_list: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[PlaceReview]]:
        if not raw_list:
            return None
        results: List[PlaceReview] = []
        for r in raw_list:
            text_obj = r.get("text", {})
            author = r.get("authorAttribution", {})
            results.append(
                PlaceReview(
                    author_name=author.get("displayName"),
                    rating=r.get("rating"),
                    text=(
                        text_obj.get("text")
                        if isinstance(text_obj, dict)
                        else text_obj
                    ),
                    publish_time=r.get("publishTime"),
                    relative_publish_time_description=r.get(
                        "relativePublishTimeDescription"
                    ),
                )
            )
        return results or None

    def _parse_response(
        self, data: Dict[str, Any], place_id: str
    ) -> PlaceDetailResult:
        """Map the full Google Details response to our canonical schema."""
        location = data.get("location", {})
        display_name_obj = data.get("displayName", {})
        editorial_obj = data.get("editorialSummary", {})
        accessibility = data.get("accessibilityOptions", {})

        opening_hours = self._parse_opening_hours(
            data.get("currentOpeningHours")
        )
        photos = self._parse_photos(data.get("photos"))
        reviews = self._parse_reviews(data.get("reviews"))

        open_now: Optional[bool] = None
        if opening_hours is not None:
            open_now = opening_hours.open_now

        return PlaceDetailResult(
            place_id=data.get("id", place_id),
            display_name=(
                display_name_obj.get("text")
                if isinstance(display_name_obj, dict)
                else display_name_obj
            ),
            formatted_address=data.get("formattedAddress"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            primary_type=data.get("primaryType"),
            types=data.get("types"),
            international_phone_number=data.get("internationalPhoneNumber"),
            national_phone_number=data.get("nationalPhoneNumber"),
            website_uri=data.get("websiteUri"),
            google_maps_uri=data.get("googleMapsUri"),
            rating=data.get("rating"),
            user_rating_count=data.get("userRatingCount"),
            business_status=data.get("businessStatus"),
            opening_hours=opening_hours,
            open_now=open_now,
            photos=photos,
            reviews=reviews,
            price_level=data.get("priceLevel"),
            wheelchair_accessible_entrance=accessibility.get(
                "wheelchairAccessibleEntrance"
            ),
            editorial_summary=(
                editorial_obj.get("text")
                if isinstance(editorial_obj, dict)
                else editorial_obj
            ),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_place_details(self, place_id: str) -> PlaceDetailResult:
        url = f"{self.base_url}/places/{place_id}"
        headers = self._build_headers()

        logger.info("Google Place Details fetch — place_id: %s", place_id)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 404:
                logger.warning(
                    "Google Place Details: place_id %s not found", place_id
                )
                raise PlaceDetailNotFoundError(place_id)

            if response.status_code == 429:
                logger.warning("Google Place Details rate limit hit")
                raise GooglePlacesRateLimitError()

            if response.status_code == 403:
                logger.error(
                    "Google Place Details forbidden — check API key. Body: %s",
                    response.text[:500],
                )
                raise GooglePlacesAPIError(
                    "Google Places API authentication failed. "
                    "Verify your API key and ensure Places API (New) is enabled."
                )

            if response.status_code != 200:
                logger.error(
                    "Google Place Details error %s for place_id %s: %s",
                    response.status_code,
                    place_id,
                    response.text[:500],
                )
                raise GooglePlacesAPIError(
                    f"Google Place Details API returned status "
                    f"{response.status_code} for place '{place_id}'"
                )

            data = response.json()
            logger.info(
                "Google Place Details fetched successfully — place_id: %s", place_id
            )
            return self._parse_response(data, place_id)

        except httpx.TimeoutException:
            logger.error(
                "Google Place Details request timed out for place_id: %s", place_id
            )
            raise GooglePlacesTimeoutError()

        except (
            PlaceDetailNotFoundError,
            GooglePlacesAPIError,
            GooglePlacesRateLimitError,
            GooglePlacesTimeoutError,
        ):
            raise  # Already mapped — re-raise as-is

        except Exception as exc:
            logger.error(
                "Unexpected error fetching Google Place Details for %s: %s",
                place_id,
                exc,
            )
            raise GooglePlacesAPIError(str(exc))
