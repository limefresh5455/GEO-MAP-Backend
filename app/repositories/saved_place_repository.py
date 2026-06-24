import logging
from typing import List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.user_saved_place import UserSavedPlace

logger = logging.getLogger(__name__)


class SavedPlaceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, saved_id: int, user_id: int) -> Optional[UserSavedPlace]:
        """Get a single saved place by its PK (with ownership check)."""
        return (
            self.db.query(UserSavedPlace)
            .filter(
                and_(
                    UserSavedPlace.id == saved_id,
                    UserSavedPlace.user_id == user_id,
                )
            )
            .first()
        )

    def create(
        self,
        *,
        user_id: int,
        place_id: str,
        display_name: Optional[str] = None,
        formatted_address: Optional[str] = None,
        primary_type: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        rating: Optional[float] = None,
        saved_location_lat: Optional[float] = None,
        saved_location_lon: Optional[float] = None,
        notes: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> UserSavedPlace:
        record = UserSavedPlace(
            user_id=user_id,
            place_id=place_id,
            display_name=display_name,
            formatted_address=formatted_address,
            primary_type=primary_type,
            latitude=latitude,
            longitude=longitude,
            rating=rating,
            saved_location_lat=saved_location_lat,
            saved_location_lon=saved_location_lon,
            notes=notes,
            tags=tags,
        )
        self.db.add(record)
        self.db.flush()
        logger.info("Saved place: user=%s place=%s", user_id, place_id)
        return record

    def update(
        self,
        record: UserSavedPlace,
        *,
        notes: Optional[str] = None,
        tags: Optional[list] = None,
        is_archived: Optional[bool] = None,
    ) -> UserSavedPlace:
        if notes is not None:
            record.notes = notes
        if tags is not None:
            record.tags = tags
        if is_archived is not None:
            record.is_archived = is_archived
        self.db.flush()
        logger.debug("Updated saved place id=%s", record.id)
        return record

    def delete(self, record: UserSavedPlace) -> None:
        """Hard delete a saved place record."""
        self.db.delete(record)
        self.db.flush()
        logger.info(
            "Unsaved place: user=%s place=%s (saved_id=%s)",
            record.user_id,
            record.place_id,
            record.id,
        )

    def delete_by_id(self, saved_id: int, user_id: int) -> Optional[UserSavedPlace]:
        """Find and hard delete a saved place by ID (with ownership check).
        Returns the deleted record or None if not found."""
        record = self.get_by_id(saved_id, user_id)
        if record:
            self.delete(record)
        return record

    def list_saved(
        self,
        user_id: int,
        *,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[UserSavedPlace], int]:
        """List user's saved places with filters. Returns (records, total_count)."""
        query = self.db.query(UserSavedPlace).filter(
            and_(
                UserSavedPlace.user_id == user_id,
                UserSavedPlace.is_archived == False,
            )
        )

        if tag:
            query = query.filter(UserSavedPlace.tags.any(tag))
        if search:
            query = query.filter(UserSavedPlace.display_name.ilike(f"%{search}%"))

        total = query.count()
        records = (
            query.order_by(UserSavedPlace.saved_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return records, total

    def count_by_user(self, user_id: int) -> int:
        """Count total saved places for a user."""
        return (
            self.db.query(func.count(UserSavedPlace.id))
            .filter(
                and_(
                    UserSavedPlace.user_id == user_id,
                    UserSavedPlace.is_archived == False,
                )
            )
            .scalar()
        ) or 0

    def get_saved_nearby_by_place_location(
        self, user_id: int, lat: float, lon: float, radius_km: float = 2.0
    ) -> List[UserSavedPlace]:
        """Find saved places where the PLACE's location is within the radius."""
        deg = radius_km / 111.0
        return (
            self.db.query(UserSavedPlace)
            .filter(
                and_(
                    UserSavedPlace.user_id == user_id,
                    UserSavedPlace.is_archived == False,
                    UserSavedPlace.latitude.isnot(None),
                    UserSavedPlace.longitude.isnot(None),
                    UserSavedPlace.latitude >= lat - deg,
                    UserSavedPlace.latitude <= lat + deg,
                    UserSavedPlace.longitude >= lon - deg,
                    UserSavedPlace.longitude <= lon + deg,
                )
            )
            .all()
        )

    def get_saved_nearby_by_save_location(
        self, user_id: int, lat: float, lon: float, radius_km: float = 2.0
    ) -> List[UserSavedPlace]:
        """Find saved places where the USER was when they saved (save context)."""
        deg = radius_km / 111.0
        return (
            self.db.query(UserSavedPlace)
            .filter(
                and_(
                    UserSavedPlace.user_id == user_id,
                    UserSavedPlace.is_archived == False,
                    UserSavedPlace.saved_location_lat.isnot(None),
                    UserSavedPlace.saved_location_lon.isnot(None),
                    UserSavedPlace.saved_location_lat >= lat - deg,
                    UserSavedPlace.saved_location_lat <= lat + deg,
                    UserSavedPlace.saved_location_lon >= lon - deg,
                    UserSavedPlace.saved_location_lon <= lon + deg,
                )
            )
            .all()
        )
