from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.location_history import LocationHistory
from app.models.user_location import UserLocation


class LocationRepository:
    """
    All direct database interactions for location data.
    Returns ORM objects or None. Never raises HTTP exceptions.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_current_location(self, user_id: int) -> Optional[UserLocation]:
        """Return the single active current location for a user, or None."""
        return (
            self.db.query(UserLocation)
            .filter(
                UserLocation.user_id == user_id,
                UserLocation.is_current == True,
                UserLocation.is_active == True,
            )
            .first()
        )

    def get_latest_location(self, user_id: int) -> Optional[UserLocation]:
        """Return the most recently created location record regardless of is_current."""
        return (
            self.db.query(UserLocation)
            .filter(UserLocation.user_id == user_id)
            .order_by(UserLocation.created_at.desc())
            .first()
        )

    def get_history(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> Tuple[List[LocationHistory], int]:
        """Return paginated location history and total record count."""
        query = (
            self.db.query(LocationHistory)
            .filter(LocationHistory.user_id == user_id)
            .order_by(LocationHistory.created_at.desc())
        )
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def deactivate_current_location(self, user_id: int) -> None:
        """Mark all current locations for a user as no longer current."""
        self.db.query(UserLocation).filter(
            UserLocation.user_id == user_id,
            UserLocation.is_current == True,
        ).update({"is_current": False}, synchronize_session=False)

    def create_location(self, user_id: int, **kwargs) -> UserLocation:
        """Insert a new UserLocation record and return it."""
        location = UserLocation(user_id=user_id, **kwargs)
        self.db.add(location)
        self.db.flush()
        return location

    def create_history_entry(
        self, user_id: int, location_id: int, **kwargs
    ) -> LocationHistory:
        """Append an immutable history record."""
        entry = LocationHistory(
            user_id=user_id,
            location_id=location_id,
            **kwargs,
        )
        self.db.add(entry)
        return entry

    def soft_delete_current(self, user_id: int) -> bool:
        """
        Logically deactivate the current location.
        Returns True if a record was found and updated.
        """
        updated = (
            self.db.query(UserLocation)
            .filter(
                UserLocation.user_id == user_id,
                UserLocation.is_current == True,
                UserLocation.is_active == True,
            )
            .update(
                {"is_current": False, "is_active": False},
                synchronize_session=False,
            )
        )
        return updated > 0
