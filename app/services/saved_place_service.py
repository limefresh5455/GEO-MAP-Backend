import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.repositories.location_repository import LocationRepository
from app.repositories.saved_place_repository import SavedPlaceRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.saved_places import SavedPlaceResponse

logger = logging.getLogger(__name__)


class SavedPlaceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SavedPlaceRepository(db)
        self.location_repo = LocationRepository(db)
        self.knowledge_repo = KnowledgeRepository(db)

    def _denormalize_place(self, place_id: str) -> dict:
        """Fetch place details from DB and return denormalized fields for saving."""
        fields = {
            "display_name": None,
            "formatted_address": None,
            "primary_type": None,
            "latitude": None,
            "longitude": None,
            "rating": None,
        }
        place = self.knowledge_repo.get_place_detail(place_id)
        if place:
            fields["display_name"] = place.display_name
            fields["formatted_address"] = place.formatted_address
            fields["primary_type"] = place.primary_type
            fields["latitude"] = place.latitude
            fields["longitude"] = place.longitude
            fields["rating"] = place.rating
        return fields

    def _get_user_location(
        self, user_id: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """Get user's current GPS location for save context. Returns (lat, lon) or (None, None)."""
        try:
            loc = self.location_repo.get_current_location(user_id)
            if loc:
                return loc.latitude, loc.longitude
        except Exception as exc:
            logger.debug("Could not fetch user location for save context: %s", exc)
        return None, None

    async def save_place(
        self,
        user_id: int,
        place_id: str,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, str, int]:
        """
        Save a place. Always creates a new record (NOT a toggle).
        Auto-captures the user's current GPS location as save context.

        Returns (success, message, saved_id).
        """
        # Denormalize place data
        place_fields = self._denormalize_place(place_id)

        # Auto-capture user's GPS location at save time
        saved_lat, saved_lon = self._get_user_location(user_id)

        record = self.repo.create(
            user_id=user_id,
            place_id=place_id,
            notes=notes,
            tags=tags,
            saved_location_lat=saved_lat,
            saved_location_lon=saved_lon,
            **place_fields,
        )
        self.db.commit()
        logger.info(
            "Place saved: user=%s place=%s saved_id=%s location=(%s, %s)",
            user_id,
            place_id,
            record.id,
            saved_lat,
            saved_lon,
        )
        return True, "Place saved successfully!", record.id

    async def unsave_place(self, saved_id: int, user_id: int) -> bool:
        """
        Explicitly unsave/remove a specific saved place entry by its ID.
        Returns True if deleted, False if not found.
        """
        record = self.repo.delete_by_id(saved_id, user_id)
        if record:
            self.db.commit()
            logger.info(
                "Place unsaved: user=%s saved_id=%s place=%s",
                user_id,
                saved_id,
                record.place_id,
            )
            return True
        logger.warning(
            "Unsave failed: saved_id=%s not found for user=%s", saved_id, user_id
        )
        return False

    async def list_saved(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        tag: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[SavedPlaceResponse], int, bool]:
        offset = (page - 1) * page_size
        records, total = self.repo.list_saved(
            user_id=user_id,
            tag=tag,
            search=search,
            limit=page_size,
            offset=offset,
        )
        has_next = (offset + page_size) < total

        items = [SavedPlaceResponse.model_validate(r) for r in records]
        return items, total, has_next

    async def update_saved(
        self,
        saved_id: int,
        user_id: int,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_archived: Optional[bool] = None,
    ) -> Optional[SavedPlaceResponse]:
        record = self.repo.get_by_id(saved_id, user_id)
        if not record:
            return None

        record = self.repo.update(
            record, notes=notes, tags=tags, is_archived=is_archived
        )
        self.db.commit()
        self.db.refresh(record)
        return SavedPlaceResponse.model_validate(record)

    async def get_saved_nearby(
        self,
        user_id: int,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        radius_km: float = 2.0,
        filter_by: str = "place",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[SavedPlaceResponse], int, bool]:
        """
        Get saved places near a location with pagination.
        Returns (items, total_count, has_next).
        """
        if lat is None or lon is None:
            loc = self.location_repo.get_current_location(user_id)
            if loc:
                lat, lon = loc.latitude, loc.longitude
                logger.info(
                    "Nearby saved places: using user's GPS location (%s, %s)",
                    lat,
                    lon,
                )
            else:
                logger.warning(
                    "Nearby saved places: no location provided and no user GPS found"
                )
                return [], 0, False

        offset = (page - 1) * page_size
        if filter_by == "saved":
            records, total = self.repo.get_saved_nearby_by_save_location(
                user_id, lat, lon, radius_km, limit=page_size, offset=offset
            )
        else:
            records, total = self.repo.get_saved_nearby_by_place_location(
                user_id, lat, lon, radius_km, limit=page_size, offset=offset
            )

        has_next = (offset + page_size) < total
        items = [SavedPlaceResponse.model_validate(r) for r in records]
        return items, total, has_next
