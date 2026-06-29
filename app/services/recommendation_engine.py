import logging
import math
from typing import Dict, List, Optional, Tuple

from app.schemas.comparison import (
    EnhancedComparisonResult,
    PlaceUserContext,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)

# ── Price Level Scoring ──────────────────────────────────────────────────

_PRICE_LEVEL_ORDER = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


def price_sort_key(level: Optional[str]) -> int:
    return _PRICE_LEVEL_ORDER.get(level, 99)


# ── Weights ──────────────────────────────────────────────────────────────

WEIGHTS = {
    "rating": 0.25,
    "popularity": 0.15,
    "price_fit": 0.20,
    "amenities": 0.20,
    "proximity": 0.10,
    "user_affinity": 0.10,
}

# ── Amenity fields to count ──────────────────────────────────────────────

_AMENITY_FIELDS = [
    "dine_in",
    "takeout",
    "delivery",
    "outdoor_seating",
    "serves_breakfast",
    "serves_lunch",
    "serves_dinner",
    "serves_beer",
    "serves_wine",
    "serves_cocktails",
    "good_for_groups",
    "good_for_children",
    "live_music",
    "reservable",
    "wheelchair_accessible",
    "parking_free",
    "payment_credit_cards",
]


class RecommendationEngine:
    """Computes weighted recommendation scores for a list of places."""

    def __init__(self) -> None:
        self.weights = WEIGHTS

    # ── Individual Score Components ──────────────────────────────────────

    def _score_rating(
        self, place: EnhancedComparisonResult, max_rating: float
    ) -> float:
        """Normalise rating 0-5 → 0-100."""
        if place.rating is None or max_rating <= 0:
            return 0.0
        return round((place.rating / max_rating) * 100.0, 1)

    def _score_popularity(
        self, place: EnhancedComparisonResult, max_count: int
    ) -> float:
        """Log-scale normalised popularity score."""
        count = place.user_rating_count or 0
        if max_count <= 0 or count <= 0:
            return 0.0
        log_count = math.log10(count + 1)
        log_max = math.log10(max_count + 1)
        return round((log_count / log_max) * 100.0, 1)

    def _score_price_fit(
        self,
        place: EnhancedComparisonResult,
        preferred_level: Optional[str],
    ) -> float:
        if place.price_level is None:
            return 50.0  # neutral

        place_level = price_sort_key(place.price_level)

        if preferred_level is None:
            # Default: moderate price gets highest, extremes lower
            preferred_level_key = price_sort_key("PRICE_LEVEL_MODERATE")
            diff = abs(place_level - preferred_level_key)
            return max(0.0, 100.0 - (diff * 25.0))

        preferred_key = price_sort_key(preferred_level)
        diff = abs(place_level - preferred_key)
        return max(0.0, 100.0 - (diff * 25.0))

    def _score_amenities(self, place: EnhancedComparisonResult) -> float:
        """Count relevant amenities as a percentage of total possible."""
        count = sum(
            1 for field in _AMENITY_FIELDS if getattr(place, field, None) is True
        )
        if count == 0:
            return 0.0
        return round((count / len(_AMENITY_FIELDS)) * 100.0, 1)

    def _score_proximity(
        self, place: EnhancedComparisonResult, max_distance: float
    ) -> float:
        distance = place.distance_from_you_km
        if distance is None:
            return 50.0  # neutral
        if max_distance <= 0:
            return 100.0
        # Invert: 0km → 100, max_distance → 0
        score = max(0.0, 100.0 - (distance / max_distance) * 100.0)
        return round(score, 1)

    def _score_user_affinity(self, ctx: Optional[PlaceUserContext]) -> float:
        if ctx is None:
            return 0.0

        score = 0.0
        if ctx.is_saved:
            score += 40.0
        if ctx.has_visited:
            score += 30.0
            # Higher personal rating = higher affinity
            if ctx.your_rating is not None:
                score += (ctx.your_rating / 5.0) * 30.0

        return round(min(score, 100.0), 1)

    # ── Inferred Price Preference ───────────────────────────────────────

    def infer_preferred_price(
        self, user_contexts: Dict[str, PlaceUserContext]
    ) -> Optional[str]:
        return None

    # Main Scoring

    def compute_scores(
        self,
        places: List[EnhancedComparisonResult],
        preferred_price_level: Optional[str] = None,
    ) -> List[Tuple[EnhancedComparisonResult, float, ScoreBreakdown]]:
        if not places:
            return []

        # Find max values for normalisation
        max_rating = max((p.rating or 0.0) for p in places)
        max_count = max((p.user_rating_count or 0) for p in places)
        max_distance = max((p.distance_from_you_km or 0.0) for p in places)

        scored: List[Tuple[EnhancedComparisonResult, float, ScoreBreakdown]] = []

        for place in places:
            rating_score = (
                self._score_rating(place, max_rating) * self.weights["rating"]
            )
            popularity_score = (
                self._score_popularity(place, max_count) * self.weights["popularity"]
            )
            price_fit_score = (
                self._score_price_fit(place, preferred_price_level)
                * self.weights["price_fit"]
            )
            amenity_score = self._score_amenities(place) * self.weights["amenities"]
            proximity_score = (
                self._score_proximity(place, max_distance) * self.weights["proximity"]
            )
            affinity_score = (
                self._score_user_affinity(place.your_context)
                * self.weights["user_affinity"]
            )

            total = round(
                rating_score
                + popularity_score
                + price_fit_score
                + amenity_score
                + proximity_score
                + affinity_score,
                1,
            )

            breakdown = ScoreBreakdown(
                rating=round(rating_score, 1),
                popularity=round(popularity_score, 1),
                price_fit=round(price_fit_score, 1),
                amenities=round(amenity_score, 1),
                proximity=round(proximity_score, 1),
                user_affinity=round(affinity_score, 1),
            )

            scored.append((place, total, breakdown))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Strengths Extraction ─────────────────────────────────────────────

    def extract_strengths(
        self,
        place: EnhancedComparisonResult,
        breakdown: ScoreBreakdown,
        all_places: List[EnhancedComparisonResult],
    ) -> List[str]:
        """
        Identify top 3 strengths for a place compared to peers.
        """
        strengths = []

        # Best rating
        if place.rating and place.rating >= 4.5:
            strengths.append("Top rated")
        elif place.rating and place.rating >= 4.0:
            strengths.append("Well rated")

        # Good value (cheapest or moderate price + good rating)
        if place.price_level in ("PRICE_LEVEL_FREE", "PRICE_LEVEL_INEXPENSIVE"):
            strengths.append("Budget friendly")
        elif place.price_level == "PRICE_LEVEL_MODERATE":
            strengths.append("Good value")

        # Popular
        if place.user_rating_count and place.user_rating_count > 500:
            strengths.append("Very popular")
        elif place.user_rating_count and place.user_rating_count > 100:
            strengths.append("Popular")

        # Open now
        if place.open_now is True:
            strengths.append("Open now")

        # Close to user
        if place.distance_from_you_km is not None and place.distance_from_you_km < 1.0:
            strengths.append("Very close")
        elif (
            place.distance_from_you_km is not None and place.distance_from_you_km < 3.0
        ):
            strengths.append("Nearby")

        # Amenities
        amenity_count = sum(
            1 for field in _AMENITY_FIELDS if getattr(place, field, None) is True
        )
        if amenity_count >= 10:
            strengths.append("Full amenities")
        elif amenity_count >= 6:
            strengths.append("Great amenities")

        # Return top 3
        return strengths[:3]
