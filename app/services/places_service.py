import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.exceptions.places import UserLocationNotFoundError
from app.integrations.google_places import GooglePlacesClient
from app.models.user_location import UserLocation
from app.repositories.redis_repository import RedisRepository
from app.schemas.places import NearbySearchRequest, PlaceResult

logger = logging.getLogger(__name__)

class PlacesService:
    def __init__(
        self,
        db: Session,
        redis_repo: RedisRepository,
        google_client: GooglePlacesClient,
    ):
        self.db = db
        self.redis_repo = redis_repo
        self.google_client = google_client

    # Internal: DB location lookup
    def _get_user_current_location(self, user_id: int) -> Optional[UserLocation]:
        return (
            self.db.query(UserLocation)
            .filter(
                UserLocation.user_id == user_id,
                UserLocation.is_current == True,
                UserLocation.is_active == True,
            )
            .first()
        )

    # Public: main search entry point
    async def search_nearby(
        self,
        request: NearbySearchRequest,
        user_id: int,
    ) -> Tuple[List[PlaceResult], bool, float, float]:
        # Step 1 — Resolve location from database
        location = self._get_user_current_location(user_id)
        if location is None:
            logger.warning(
                "Nearby search blocked — user_id %s has no saved location",
                user_id,
            )
            raise UserLocationNotFoundError()

        latitude = location.latitude
        longitude = location.longitude

        logger.info(
            "Nearby search — user_id: %s, source: %s, lat: %s, lon: %s, radius: %sm",
            user_id,
            location.source,
            latitude,
            longitude,
            request.radius,
        )

        # Step 2 — Generate user-scoped cache key
        cache_key = self.redis_repo.generate_nearby_cache_key(
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            max_result_count=request.max_result_count,
        )

        # Step 3 — Check Redis
        cached = await self.redis_repo.get(cache_key)
        if cached is not None:
            logger.info(
                "Cache HIT for user_id: %s, key: %s", user_id, cache_key
            )
            places = [PlaceResult(**item) for item in cached]
            return places, True, latitude, longitude

        # Step 4 — Cache miss: call Google Places API
        logger.info(
            "Cache MISS for user_id: %s — calling Google Places API", user_id
        )
        places = await self.google_client.search_nearby(
            latitude=latitude,
            longitude=longitude,
            radius=request.radius,
            max_result_count=request.max_result_count,
        )

        # Step 5 — Persist to Redis
        serialisable = [p.model_dump() for p in places]
        await self.redis_repo.set(cache_key, serialisable)

        return places, False, latitude, longitude
