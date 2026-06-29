import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.saved_place_repository import SavedPlaceRepository
from app.repositories.visit_repository import VisitRepository
from app.repositories.location_repository import LocationRepository
from app.schemas.comparison import (
    AttributeColumn,
    AttributeValue,
    CompareBasicResponse,
    CompareRecommendResponse,
    EnhancedComparisonResult,
    PhotoReference,
    PlaceUserContext,
    RecommendationResult,
    ReviewSummary,
    ScoreBreakdown,
)
from app.services.recommendation_engine import RecommendationEngine, price_sort_key

logger = logging.getLogger(__name__)

# ── Haversine distance ───────────────────────────────────────────────────

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in km between two coordinate pairs."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(_EARTH_RADIUS_KM * c, 2)


# ── Attribute labels ─────────────────────────────────────────────────────

_ATTRIBUTE_DEFINITIONS: List[Tuple[str, str, str]] = [
    ("rating", "Rating", "numeric"),
    ("user_rating_count", "Reviews", "numeric"),
    ("price_level", "Price Level", "text"),
    ("business_status", "Status", "text"),
    ("open_now", "Open Now", "bool"),
    ("primary_type", "Type", "text"),
    ("wheelchair_accessible", "Wheelchair Accessible", "bool"),
    ("dine_in", "Dine-In", "bool"),
    ("takeout", "Takeout", "bool"),
    ("delivery", "Delivery", "bool"),
    ("outdoor_seating", "Outdoor Seating", "bool"),
    ("serves_breakfast", "Breakfast", "bool"),
    ("serves_lunch", "Lunch", "bool"),
    ("serves_dinner", "Dinner", "bool"),
    ("serves_beer", "Beer", "bool"),
    ("serves_wine", "Wine", "bool"),
    ("serves_cocktails", "Cocktails", "bool"),
    ("good_for_children", "Good for Children", "bool"),
    ("good_for_groups", "Good for Groups", "bool"),
    ("live_music", "Live Music", "bool"),
    ("reservable", "Reservations", "bool"),
    ("parking_free", "Free Parking", "bool"),
    ("parking_paid", "Paid Parking", "bool"),
    ("ev_charging", "EV Charging", "bool"),
    ("payment_credit_cards", "Cards Accepted", "bool"),
    ("distance_from_you_km", "Distance", "numeric"),
]


_PRICE_LABELS: Dict[str, str] = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


class ComparisonService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.knowledge_repo = KnowledgeRepository(db)
        self.saved_place_repo = SavedPlaceRepository(db)
        self.visit_repo = VisitRepository(db)
        self.location_repo = LocationRepository(db)
        self.recommendation_engine = RecommendationEngine()

    # ── User Context Builder (Batch) ─────────────────────────────────────

    def _build_batch_user_contexts(
        self, user_id: int, place_ids: List[str]
    ) -> Dict[str, PlaceUserContext]:
        """
        Batch-load saved places and visit data for ALL place_ids at once,
        avoiding N+1 queries (2 queries total instead of 2 per place).
        """
        # Batch query 1: all saved places for this user matching these place_ids
        saved_by_place = {}
        try:
            saved_records = self.saved_place_repo.get_saved_by_place_ids(
                user_id, place_ids
            )
            for record in saved_records:
                saved_by_place[record.place_id] = record
        except Exception as exc:
            logger.debug("Batch load saved places failed: %s", exc)

        # Batch query 2: latest visit per place for this user
        latest_visits = {}
        try:
            visit_records = self.visit_repo.get_latest_visits_by_place_ids(
                user_id, place_ids
            )
            for record in visit_records:
                latest_visits[record.place_id] = record
        except Exception as exc:
            logger.debug("Batch load visits failed: %s", exc)

        contexts = {}
        for pid in place_ids:
            ctx = PlaceUserContext()

            saved = saved_by_place.get(pid)
            if saved:
                ctx.is_saved = True
                ctx.saved_id = saved.id
                ctx.saved_at = saved.saved_at
                ctx.tags = saved.tags
                ctx.notes = saved.notes

            visit = latest_visits.get(pid)
            if visit:
                ctx.has_visited = True
                ctx.visited_at = visit.visited_at
                ctx.your_rating = visit.rating_given
                ctx.your_review = visit.review_text
                ctx.visit_mood = visit.mood
                ctx.visited_with = visit.with_whom

            contexts[pid] = ctx

        return contexts

    # ── User Location ────────────────────────────────────────────────────

    def _get_user_gps(self, user_id: int) -> Tuple[Optional[float], Optional[float]]:
        """Get the user's current GPS location. Returns (lat, lon) or (None, None)."""
        try:
            loc = self.location_repo.get_current_location(user_id)
            if loc:
                return loc.latitude, loc.longitude
        except Exception as exc:
            logger.warning("Could not fetch user GPS for comparison: %s", exc)
        return None, None

    # ── Place to EnhancedComparisonResult ────────────────────────────────

    def _place_to_enhanced(
        self,
        place_id: str,
        user_id: int,
        batch_contexts: Dict[str, PlaceUserContext],
        user_lat: Optional[float] = None,
        user_lon: Optional[float] = None,
    ) -> Optional[EnhancedComparisonResult]:
        """Fetch place details and map to EnhancedComparisonResult."""
        place = self.knowledge_repo.get_place_detail(place_id)
        if not place:
            return None

        extended = place.extended_data or {}
        context = batch_contexts.get(place_id, PlaceUserContext())

        result = EnhancedComparisonResult(
            place_id=place.place_id,
            display_name=place.display_name,
            formatted_address=place.formatted_address,
            primary_type=place.primary_type,
            types=place.types,
            latitude=place.latitude,
            longitude=place.longitude,
            rating=place.rating,
            user_rating_count=place.user_rating_count,
            price_level=place.price_level,
            business_status=place.business_status,
            open_now=place.open_now,
            wheelchair_accessible=place.wheelchair_accessible_entrance,
            website_uri=place.website_uri,
            phone_number=place.international_phone_number
            or place.national_phone_number,
            google_maps_uri=place.google_maps_uri,
            editorial_summary=place.editorial_summary,
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
            allows_dogs=extended.get("allowsDogs"),
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
            # User context
            your_context=context,
        )

        # Opening hours summary
        oh = place.opening_hours
        if oh:
            if isinstance(oh, dict):
                descs = oh.get("weekday_descriptions")
            else:
                descs = getattr(oh, "weekday_descriptions", None)
            if descs:
                result.opening_hours_summary = "; ".join(descs[:3])

        # Photos (NEW — up to 3)
        if place.photos and isinstance(place.photos, (list, tuple)):
            photos = []
            for photo in place.photos[:3]:
                if isinstance(photo, dict):
                    photos.append(
                        PhotoReference(
                            name=photo.get("name"),
                            width_px=photo.get("widthPx"),
                            height_px=photo.get("heightPx"),
                        )
                    )
            result.photo_references = photos or None

        # Reviews (NEW — top 3 with text)
        if place.reviews and isinstance(place.reviews, (list, tuple)):
            reviews = []
            for review in place.reviews[:3]:
                if isinstance(review, dict):
                    text_obj = review.get("text", {})
                    text = (
                        text_obj.get("text") if isinstance(text_obj, dict) else text_obj
                    )
                    reviews.append(
                        ReviewSummary(
                            author_name=review.get("authorAttribution", {}).get(
                                "displayName"
                            ),
                            rating=review.get("rating"),
                            text=text,
                            relative_time=review.get("relativePublishTimeDescription"),
                        )
                    )
            result.top_reviews = reviews or None

        # Distance from user
        if (
            user_lat is not None
            and user_lon is not None
            and place.latitude is not None
            and place.longitude is not None
        ):
            result.distance_from_you_km = _haversine_km(
                user_lat, user_lon, place.latitude, place.longitude
            )

        return result

    # ── Attribute Table Builder ──────────────────────────────────────────

    def _build_attribute_table(
        self, places: List[EnhancedComparisonResult]
    ) -> List[AttributeColumn]:
        """Build side-by-side attribute columns from a list of places."""
        columns: List[AttributeColumn] = []

        for key, label, _type in _ATTRIBUTE_DEFINITIONS:
            values: List[AttributeValue] = []
            for place in places:
                raw_value = getattr(place, key, None)
                display_label = None

                # Format special values
                if key == "price_level" and raw_value:
                    display_label = _PRICE_LABELS.get(raw_value, raw_value)
                elif key == "distance_from_you_km" and raw_value is not None:
                    display_label = f"{raw_value} km"
                elif key == "business_status" and raw_value:
                    display_label = raw_value.replace("_", " ").title()
                elif key == "open_now":
                    display_label = (
                        "Yes" if raw_value else "No" if raw_value is False else None
                    )

                values.append(
                    AttributeValue(
                        place_id=place.place_id,
                        value=raw_value,
                        label=display_label,
                    )
                )

            # Only include column if at least one place has a non-None value
            if any(v.value is not None for v in values):
                columns.append(AttributeColumn(key=key, label=label, values=values))

        return columns

    # ── Highlights Builder ───────────────────────────────────────────────

    def _compute_highlights(
        self, results: List[EnhancedComparisonResult]
    ) -> Dict[str, Any]:
        """Identify best-in-class values across compared places."""
        highlights: Dict[str, Any] = {}

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

        # Most reviews
        reviewed = [r for r in results if r.user_rating_count is not None]
        if reviewed:
            most = max(reviewed, key=lambda r: r.user_rating_count or 0)
            highlights["most_reviews"] = {
                "place_id": most.place_id,
                "name": most.display_name,
                "count": most.user_rating_count,
            }

        # Best value (cheapest with decent rating)
        priced = [
            r
            for r in results
            if r.price_level is not None and r.rating is not None and r.rating >= 3.5
        ]
        if priced:
            cheapest = min(priced, key=lambda r: price_sort_key(r.price_level))
            highlights["best_value"] = {
                "place_id": cheapest.place_id,
                "name": cheapest.display_name,
                "price_level": _PRICE_LABELS.get(
                    cheapest.price_level, cheapest.price_level
                ),
                "rating": cheapest.rating,
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

        # Closest to user
        with_distance = [r for r in results if r.distance_from_you_km is not None]
        if with_distance:
            closest = min(with_distance, key=lambda r: r.distance_from_you_km or 999)
            highlights["closest_to_you"] = {
                "place_id": closest.place_id,
                "name": closest.display_name,
                "distance_km": closest.distance_from_you_km,
            }

        return highlights

    # ── AI Summary Generator ─────────────────────────────────────────────

    async def _generate_ai_summary(
        self,
        ranked: List[Tuple[EnhancedComparisonResult, float, ScoreBreakdown]],
    ) -> str:
        """
        Use OpenAI to generate a natural-language comparison summary.
        Falls back to a template-based summary if OpenAI is unavailable.
        """
        try:
            from app.core.config import settings
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

            place_lines = []
            for i, (place, score, breakdown) in enumerate(ranked[:5], 1):
                place_lines.append(
                    f"{i}. {place.display_name or 'Unknown'} "
                    f"(Score: {score}/100, Rating: {place.rating or 'N/A'}, "
                    f"Price: {place.price_level or 'N/A'}, "
                    f"Distance: {place.distance_from_you_km or 'N/A'} km)"
                )

            prompt = (
                "You are a travel recommendation assistant. "
                "Compare the following places and write 2-3 sentences explaining "
                "why each is ranked where it is. Be concise and helpful.\n\n"
                + "\n".join(place_lines)
                + "\n\nWrite a brief natural-language comparison summary."
            )

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7,
            )

            summary = response.choices[0].message.content or ""
            return summary.strip()
        except Exception as exc:
            logger.warning("AI comparison summary failed: %s", exc)
            return self._fallback_summary(ranked)

    def _fallback_summary(
        self,
        ranked: List[Tuple[EnhancedComparisonResult, float, ScoreBreakdown]],
    ) -> str:
        """Template-based fallback summary when AI is unavailable."""
        if not ranked:
            return "No places to compare."

        top = ranked[0][0]
        top_score = ranked[0][1]
        parts = [
            f"{top.display_name or 'The top place'} is recommended with a score of {top_score}/100."
        ]

        if len(ranked) > 1:
            second = ranked[1][0]
            second_score = ranked[1][1]
            diff = round(top_score - second_score, 1)
            if diff > 10:
                parts.append(
                    f"It significantly outperforms {second.display_name or 'the next option'} "
                    f"by {diff} points."
                )
            else:
                parts.append(
                    f"{second.display_name or 'The second option'} is a close alternative "
                    f"with a score of {second_score}."
                )

        return " ".join(parts)

    # ── Public: Compare Basic (Side-by-Side) ─────────────────────────────

    async def compare_basic(
        self,
        place_ids: List[str],
        user_id: int,
    ) -> CompareBasicResponse:
        """
        Side-by-side comparison of multiple places with:
        - All attributes in a structured table
        - User context (saved + visit)
        - Reviews, photos
        - Distance from user's GPS
        - Highlights
        """
        user_lat, user_lon = self._get_user_gps(user_id)

        # Batch-load user context for ALL places at once (avoids N+1)
        batch_contexts = self._build_batch_user_contexts(user_id, place_ids)

        results: List[EnhancedComparisonResult] = []
        not_found: List[str] = []

        for pid in place_ids:
            result = self._place_to_enhanced(
                pid, user_id, batch_contexts, user_lat, user_lon
            )
            if result:
                results.append(result)
            else:
                not_found.append(pid)

        if not results:
            return CompareBasicResponse(
                success=False,
                message="None of the requested places were found. Fetch place details first.",
                places=[],
                attribute_table=[],
                highlights=None,
                total_places=0,
                user_location_used=(user_lat is not None),
            )

        # Build attribute table
        attribute_table = self._build_attribute_table(results)

        # Build highlights
        highlights = self._compute_highlights(results)

        msg = f"Compared {len(results)} place(s)." + (
            f" {len(not_found)} place(s) not found: {', '.join(not_found)}"
            if not_found
            else ""
        )

        return CompareBasicResponse(
            success=True,
            message=msg,
            places=results,
            attribute_table=attribute_table,
            highlights=highlights,
            total_places=len(results),
            user_location_used=(user_lat is not None),
        )

    # ── Public: Recommend (AI-Powered Ranking) ───────────────────────────

    async def recommend(
        self,
        place_ids: List[str],
        user_id: int,
        use_ai_summary: bool = True,
    ) -> CompareRecommendResponse:
        """
        Rank places from best to worst for this specific user.
        Uses weighted scoring + optional AI summary.
        """
        user_lat, user_lon = self._get_user_gps(user_id)

        # Batch-load user context for ALL places at once (avoids N+1)
        batch_contexts = self._build_batch_user_contexts(user_id, place_ids)

        results: List[EnhancedComparisonResult] = []
        not_found: List[str] = []

        for pid in place_ids:
            result = self._place_to_enhanced(
                pid, user_id, batch_contexts, user_lat, user_lon
            )
            if result:
                results.append(result)
            else:
                not_found.append(pid)

        if not results:
            return CompareRecommendResponse(
                success=False,
                message="None of the requested places were found.",
                recommendations=[],
                total_places_compared=0,
            )

        # Compute weighted scores
        scored = self.recommendation_engine.compute_scores(results)

        # Build ranked recommendations
        recommendations: List[RecommendationResult] = []
        for rank, (place, score, breakdown) in enumerate(scored, 1):
            strengths = self.recommendation_engine.extract_strengths(
                place, breakdown, results
            )

            photos = None
            if place.photo_references:
                photos = place.photo_references[:2]

            recommendations.append(
                RecommendationResult(
                    rank=rank,
                    place_id=place.place_id,
                    display_name=place.display_name,
                    primary_type=place.primary_type,
                    formatted_address=place.formatted_address,
                    latitude=place.latitude,
                    longitude=place.longitude,
                    rating=place.rating,
                    price_level=place.price_level,
                    photo_references=photos,
                    overall_score=score,
                    score_breakdown=breakdown,
                    strengths=strengths,
                    your_context=place.your_context,
                )
            )

        # Generate AI summary
        overall_summary: Optional[str] = None
        if use_ai_summary:
            overall_summary = await self._generate_ai_summary(scored)

        msg = f"Compared and ranked {len(recommendations)} place(s)." + (
            f" {len(not_found)} place(s) not found: {', '.join(not_found)}"
            if not_found
            else ""
        )

        return CompareRecommendResponse(
            success=True,
            message=msg,
            recommendations=recommendations,
            overall_ai_summary=overall_summary,
            total_places_compared=len(recommendations),
        )
