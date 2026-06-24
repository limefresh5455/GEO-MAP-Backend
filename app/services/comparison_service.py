import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.comparison import (
    ComparePlacesResponse,
    ComparisonResult,
)

logger = logging.getLogger(__name__)


class ComparisonService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.knowledge_repo = KnowledgeRepository(db)

    def _place_to_comparison(self, place_id: str) -> Optional[ComparisonResult]:
        """Fetch place details from DB and map to ComparisonResult fields."""
        place = self.knowledge_repo.get_place_detail(place_id)
        if not place:
            return None

        extended = place.extended_data or {}

        result = ComparisonResult(
            place_id=place.place_id,
            display_name=place.display_name,
            formatted_address=place.formatted_address,
            primary_type=place.primary_type,
            latitude=place.latitude,
            longitude=place.longitude,
            rating=place.rating,
            user_rating_count=place.user_rating_count,
            price_level=place.price_level,
            business_status=place.business_status,
            open_now=place.open_now,
            opening_hours_summary=None,
            wheelchair_accessible=place.wheelchair_accessible_entrance,
            website_uri=place.website_uri,
            phone_number=place.international_phone_number
            or place.national_phone_number,
            editorial_summary=place.editorial_summary,
            photo_name=None,
            # Extended amenities
            dine_in=extended.get("dineIn"),
            takeout=extended.get("takeout"),
            delivery=extended.get("delivery"),
            curbside_pickup=extended.get("curbsidePickup"),
            serves_breakfast=extended.get("servesBreakfast"),
            serves_lunch=extended.get("servesLunch"),
            serves_dinner=extended.get("servesDinner"),
            serves_brunch=extended.get("servesBrunch"),
            serves_beer=extended.get("servesBeer"),
            serves_wine=extended.get("servesWine"),
            serves_cocktails=extended.get("servesCocktails"),
            serves_vegetarian_food=extended.get("servesVegetarianFood"),
            outdoor_seating=extended.get("outdoorSeating"),
            restroom=extended.get("restroom"),
            good_for_children=extended.get("goodForChildren"),
            good_for_groups=extended.get("goodForGroups"),
            live_music=extended.get("liveMusic"),
            reservable=extended.get("reservable"),
            parking_free=extended.get("parking_free"),
            parking_paid=extended.get("parking_paid"),
            parking_valet=extended.get("parking_valet"),
            ev_charging=extended.get("ev_charging"),
            payment_cash=extended.get("payment_cash"),
            payment_credit_cards=extended.get("payment_credit_cards"),
            payment_contactless=extended.get("payment_contactless"),
            payment_nfc=extended.get("payment_nfc"),
            wikipedia_extract=extended.get("wikipedia_extract"),
            neighborhood=extended.get("neighborhood") or extended.get("osm_suburb"),
        )

        # Extract opening hours summary
        oh = place.opening_hours
        if oh:
            # opening_hours can be a dict (from JSON column) or a Pydantic model
            if isinstance(oh, dict):
                descs = oh.get("weekday_descriptions")
            else:
                descs = getattr(oh, "weekday_descriptions", None)
            if descs:
                result.opening_hours_summary = "; ".join(descs[:3])

        # Extract first photo name
        if (
            place.photos
            and isinstance(place.photos, (list, tuple))
            and len(place.photos) > 0
        ):
            photo = place.photos[0]
            if isinstance(photo, dict):
                result.photo_name = photo.get("name")

        return result

    def _compute_highlights(self, results: List[ComparisonResult]) -> Dict[str, Any]:
        """Identify best-in-class values across compared places."""
        highlights = {}

        # Best rating
        rated = [r for r in results if r.rating is not None]
        if rated:
            best_rated = max(rated, key=lambda r: (r.rating, r.user_rating_count or 0))
            highlights["highest_rated"] = {
                "place_id": best_rated.place_id,
                "name": best_rated.display_name,
                "rating": best_rated.rating,
                "review_count": best_rated.user_rating_count,
            }

        # Best price level (lowest = cheapest value)
        priced = [r for r in results if r.price_level is not None]
        if priced:
            cheapest = min(priced, key=lambda r: _price_level_sort_key(r.price_level))
            highlights["best_value"] = {
                "place_id": cheapest.place_id,
                "name": cheapest.display_name,
                "price_level": cheapest.price_level,
            }

        # Most amenities
        amenity_fields = [
            "dine_in",
            "takeout",
            "delivery",
            "outdoor_seating",
            "serves_breakfast",
            "serves_lunch",
            "serves_dinner",
            "serves_beer",
            "serves_wine",
            "good_for_groups",
            "live_music",
            "reservable",
        ]
        amenity_counts = []
        for r in results:
            count = sum(
                1 for field in amenity_fields if getattr(r, field, None) is True
            )
            amenity_counts.append((r.place_id, r.display_name, count))

        if amenity_counts:
            most_amenities = max(amenity_counts, key=lambda x: x[2])
            if most_amenities[2] > 0:
                highlights["most_amenities"] = {
                    "place_id": most_amenities[0],
                    "name": most_amenities[1],
                    "count": most_amenities[2],
                }

        return highlights

    async def compare(
        self,
        place_ids: List[str],
        fields: Optional[List[str]] = None,
    ) -> ComparePlacesResponse:
        """Compare multiple places side-by-side, optionally filtering attributes."""
        results = []
        not_found = []

        for pid in place_ids:
            result = self._place_to_comparison(pid)
            if result:
                results.append(result)
            else:
                not_found.append(pid)

        if not results:
            return ComparePlacesResponse(
                success=False,
                message="None of the requested places were found. Fetch place details first.",
                comparison=[],
                highlights=None,
                total_places=0,
            )

        highlights = self._compute_highlights(results)

        msg = f"Compared {len(results)} place(s)." + (
            f" {len(not_found)} place(s) not found: {', '.join(not_found)}"
            if not_found
            else ""
        )

        return ComparePlacesResponse(
            success=True,
            message=msg,
            comparison=results,
            highlights=highlights,
            total_places=len(results),
        )


def _price_level_sort_key(level: Optional[str]) -> int:
    """Convert price level string to sortable int (lower = cheaper)."""
    mapping = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    return mapping.get(level, 99)
