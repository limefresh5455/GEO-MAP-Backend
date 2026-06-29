from typing import List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.location_history import LocationHistory
from app.models.user_location import UserLocation


class LocationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_current_location(self, user_id: int) -> Optional[UserLocation]:
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
        return (
            self.db.query(UserLocation)
            .filter(UserLocation.user_id == user_id)
            .order_by(UserLocation.created_at.desc())
            .first()
        )

    def get_history(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> Tuple[List[LocationHistory], int]:
        count_col = func.count(LocationHistory.id).over().label("total_count")
        rows = (
            self.db.query(LocationHistory, count_col)
            .filter(LocationHistory.user_id == user_id)
            .order_by(LocationHistory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        if not rows:
            return [], 0
        items = [row[0] for row in rows]
        total = rows[0][1]
        return items, total

    # Writes

    def deactivate_current_location(self, user_id: int) -> None:
        self.db.query(UserLocation).filter(
            UserLocation.user_id == user_id,
            UserLocation.is_current == True,
        ).update({"is_current": False}, synchronize_session="evaluate")

    def create_location(self, user_id: int, **kwargs) -> UserLocation:
        location = UserLocation(user_id=user_id, **kwargs)
        self.db.add(location)
        self.db.flush()
        return location

    def create_history_entry(
        self, user_id: int, location_id: int, **kwargs
    ) -> LocationHistory:
        entry = LocationHistory(
            user_id=user_id,
            location_id=location_id,
            **kwargs,
        )
        self.db.add(entry)
        return entry

    def soft_delete_current(self, user_id: int) -> bool:
        updated = (
            self.db.query(UserLocation)
            .filter(
                UserLocation.user_id == user_id,
                UserLocation.is_current == True,
                UserLocation.is_active == True,
            )
            .update(
                {"is_current": False, "is_active": False},
                synchronize_session="evaluate",
            )
        )
        return updated > 0

    def get_history_by_id(
        self, user_id: int, history_id: int
    ) -> Optional[LocationHistory]:
        return (
            self.db.query(LocationHistory)
            .filter(
                LocationHistory.id == history_id,
                LocationHistory.user_id == user_id,
            )
            .first()
        )

    def delete_history_entry(self, entry: LocationHistory) -> None:
        self.db.delete(entry)
        self.db.flush()
