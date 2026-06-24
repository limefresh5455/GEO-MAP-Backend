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

DETAILS_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "types",
        "primaryType",
        "businessStatus",
        "currentOpeningHours",
        "regularOpeningHours",
        "regularSecondaryOpeningHours",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "websiteUri",
        "googleMapsUri",
        "rating",
        "userRatingCount",
        "priceLevel",
        "editorialSummary",
        "photos",
        "reviews",
        "accessibilityOptions",
        "parkingOptions",
        "paymentOptions",
        "dineIn",
        "takeout",
        "delivery",
        "curbsidePickup",
        "reservable",
        "servesBreakfast",
        "servesLunch",
        "servesDinner",
        "servesBeer",
        "servesWine",
        "servesCocktails",
        "outdoorSeating",
        "liveMusic",
        "goodForChildren",
        "goodForGroups",
        "restroom",
        "allowsDogs",
        "utcOffsetMinutes",
        "plusCode",
        "addressComponents",
        "evChargeOptions",
        "subDestinations",
    ]
)


class GooglePlaceDetailsClient:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.base_url = settings.GOOGLE_PLACES_BASE_URL
        self._http_client = http_client
        self._timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

    def _build_headers(self) -> Dict[str, str]:
        return {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": DETAILS_FIELD_MASK,
        }

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
                        text_obj.get("text") if isinstance(text_obj, dict) else text_obj
                    ),
                    publish_time=r.get("publishTime"),
                    relative_publish_time_description=r.get(
                        "relativePublishTimeDescription"
                    ),
                )
            )
        return results or None

    def _parse_response(
        self, data: Dict[str, Any], requested_place_id: str
    ) -> PlaceDetailResult:
        google_returned_id = data.get("id")
        if google_returned_id and google_returned_id != requested_place_id:
            logger.info(
                "Place ID canonicalised by Google: requested=%s canonical=%s — "
                "storing as requested id to preserve lookup consistency (B15/B-033)",
                requested_place_id,
                google_returned_id,
            )
            # B-033 FIX: Store canonical ID in editorial summary metadata
            editorial_obj = data.get("editorialSummary", {})
            editorial_text = (
                editorial_obj.get("text")
                if isinstance(editorial_obj, dict)
                else editorial_obj
            )
            if editorial_text:
                editorial_text = (
                    f"{editorial_text} [canonical_id: {google_returned_id}]"
                )
            data["editorialSummary"] = (
                {"text": editorial_text} if editorial_text else editorial_obj
            )

        location = data.get("location", {})
        display_name_obj = data.get("displayName", {})
        editorial_obj = data.get("editorialSummary", {})
        accessibility = data.get("accessibilityOptions", {})
        parking = data.get("parkingOptions", {})
        payment = data.get("paymentOptions", {})
        ev = data.get("evChargeOptions", {})

        opening_hours = self._parse_opening_hours(data.get("currentOpeningHours"))
        photos = self._parse_photos(data.get("photos"))
        reviews = self._parse_reviews(data.get("reviews"))

        open_now: Optional[bool] = None
        if opening_hours is not None:
            open_now = opening_hours.open_now

        # Collect all extended fields into a single dict
        extended: Dict[str, Any] = {}

        # Regular + secondary opening hours (raw dict for enrichment)
        regular_hours = data.get("regularOpeningHours")
        if regular_hours:
            extended["regular_opening_hours"] = regular_hours
        secondary_hours = data.get("regularSecondaryOpeningHours")
        if secondary_hours:
            extended["secondary_opening_hours"] = secondary_hours

        # Parking
        if parking:
            for k, v in parking.items():
                extended[f"parking_{k}"] = v

        # Payment
        if payment:
            for k, v in payment.items():
                extended[f"payment_{k}"] = v

        # Dining / service flags
        for flag in ["dineIn", "takeout", "delivery", "curbsidePickup", "reservable"]:
            val = data.get(flag)
            if val is not None:
                extended[flag] = val

        # Food & drink
        for flag in [
            "servesBreakfast",
            "servesLunch",
            "servesDinner",
            "servesBeer",
            "servesWine",
            "servesCocktails",
        ]:
            val = data.get(flag)
            if val is not None:
                extended[flag] = val

        # Atmosphere / features
        for flag in [
            "outdoorSeating",
            "liveMusic",
            "goodForChildren",
            "goodForGroups",
            "restroom",
            "allowsDogs",
        ]:
            val = data.get(flag)
            if val is not None:
                extended[flag] = val

        # EV charging
        if ev:
            extended["ev_charger_options"] = ev

        # Timezone
        utc_offset = data.get("utcOffsetMinutes")
        if utc_offset is not None:
            extended["utc_offset_minutes"] = utc_offset

        # Plus code
        plus_code = data.get("plusCode", {})
        if plus_code:
            extended["plus_code"] = plus_code.get("globalCode") or plus_code.get(
                "compoundCode"
            )

        # Address components (for neighborhood, locality extraction)
        addr_components = data.get("addressComponents", [])
        if addr_components:
            neighborhoods = []
            localities = []
            sublocalities = []
            for comp in addr_components:
                types_list = comp.get("types", [])
                text = comp.get("longText") or ""
                if "neighborhood" in types_list:
                    neighborhoods.append(text)
                if "locality" in types_list:
                    localities.append(text)
                if "sublocality" in types_list:
                    sublocalities.append(text)
            if neighborhoods:
                extended["neighborhood"] = neighborhoods[0]
            if localities:
                extended["locality"] = localities[0]
            if sublocalities:
                extended["sublocality"] = sublocalities[0]

        # Sub destinations (airport terminals, mall sections, park zones)
        sub_destinations = data.get("subDestinations", [])
        if sub_destinations:
            extended["sub_destinations"] = [
                {
                    "name": (
                        sd.get("name", {}).get("text")
                        if isinstance(sd.get("name"), dict)
                        else sd.get("name")
                    ),
                    "place_id": sd.get("id"),
                }
                for sd in sub_destinations
                if sd.get("name") or sd.get("id")
            ]

        return PlaceDetailResult(
            # B15: Always use the requested id as the key, not Google's canonical
            place_id=requested_place_id,
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
            extended_data=extended if extended else None,
        )

    async def _do_request(self, url: str, headers: Dict) -> httpx.Response:

        if self._http_client is not None:
            return await self._http_client.get(url, headers=headers)

        # B-030 FIX: Log warning for fallback usage
        logger.warning(
            "GooglePlaceDetailsClient: No shared HTTP client - creating per-request client. "
            "This should only happen in tests."
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.get(url, headers=headers)

    async def get_place_details(self, place_id: str) -> PlaceDetailResult:
        url = f"{self.base_url}/places/{place_id}"
        headers = self._build_headers()

        logger.info("Google Place Details fetch — place_id: %s", place_id)

        try:
            response = await self._do_request(url, headers)

            if response.status_code == 404:
                logger.warning("Google Place Details: place_id %s not found", place_id)
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
                error_body = (
                    response.text[:1000] if response.text else "No response body"
                )
                logger.error(
                    "Google Place Details error %s for place_id %s: %s",
                    response.status_code,
                    place_id,
                    error_body,
                )

                # Try to parse the actual Google error message from the response
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", {}).get(
                        "message", error_body
                    )
                    logger.error(
                        "Google API error details — message: %s",
                        error_message,
                    )
                except Exception:
                    error_message = error_body

                # If Google says the place doesn't exist ("not found" / "NOT_FOUND"),
                # raise 404 instead of 502 for a better client experience
                is_not_found = any(
                    keyword in str(error_message).lower()
                    for keyword in [
                        "not found",
                        "not_found",
                        "does not exist",
                        "notexist",
                    ]
                )
                if response.status_code == 404 or (
                    response.status_code == 400 and is_not_found
                ):
                    raise PlaceDetailNotFoundError(place_id)

                raise GooglePlacesAPIError(
                    f"Google Place Details API returned status "
                    f"{response.status_code} for place '{place_id}': {error_message}"
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
            raise

        except Exception as exc:
            logger.error(
                "Unexpected error fetching Google Place Details for %s: %s",
                place_id,
                exc,
            )
            raise GooglePlacesAPIError(str(exc))
