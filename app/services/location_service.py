import logging
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions.custom_exceptions import LocationNotFoundError
from app.models.user_location import UserLocation
from app.repositories.location_repository import LocationRepository
from app.schemas.location import GPSUpdateRequest, ManualUpdateRequest
from app.validators.location_validator import (
    is_duplicate_location,
    validate_accuracy,
    validate_coordinates,
)

logger = logging.getLogger(__name__)


class LocationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = LocationRepository(db)

    # ------------------------------------------------------------------
    # GPS Update (auto from client)
    # ------------------------------------------------------------------

    def _do_gps_write(
        self, user_id: int, payload: GPSUpdateRequest
    ) -> Tuple[UserLocation, bool]:
    
        existing = self.repo.get_current_location(user_id)

        if existing and is_duplicate_location(
            payload.latitude, payload.longitude,
            existing.latitude, existing.longitude,
        ):
            return existing, True

        self.repo.deactivate_current_location(user_id)

        new_location = self.repo.create_location(
            user_id=user_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
            altitude=payload.altitude,
            speed=payload.speed,
            source="gps",
            is_current=True,
            is_active=True,
            client_timestamp=payload.client_timestamp,
            metadata_notes=payload.metadata_notes,
        )

        self.repo.create_history_entry(
            user_id=user_id,
            location_id=new_location.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
            altitude=payload.altitude,
            speed=payload.speed,
            source="gps",
        )

        self.db.commit()
        self.db.refresh(new_location)
        return new_location, False

    def process_gps_update(
        self, user_id: int, payload: GPSUpdateRequest
    ) -> Tuple[UserLocation, bool]:
        
        validate_coordinates(payload.latitude, payload.longitude)
        validate_accuracy(payload.accuracy)

        try:
            return self._do_gps_write(user_id, payload)
        except IntegrityError as e:
            # B042 FIX: Check which constraint failed to avoid masking other errors.
            # Only retry if the unique current location constraint was violated.
            constraint_name = "uix_user_locations_single_current"
            if constraint_name in str(e.orig):
                # B09: Lost the race — another concurrent request already committed
                # a new is_current=True row. Roll back and retry once.
                logger.warning(
                    "GPS update IntegrityError for user_id=%s — concurrent write "
                    "detected on %s constraint, retrying once.", user_id, constraint_name
                )
                self.db.rollback()
                return self._do_gps_write(user_id, payload)
            else:
                # Different constraint violation — re-raise so it's not masked
                logger.error(
                    "GPS update IntegrityError for user_id=%s — NOT a race condition: %s",
                    user_id, str(e)
                )
                raise

    # ------------------------------------------------------------------
    # Manual Update
    # ------------------------------------------------------------------

    def process_manual_update(
        self, user_id: int, payload: ManualUpdateRequest
    ) -> UserLocation:
        
        validate_coordinates(payload.latitude, payload.longitude)
        validate_accuracy(payload.accuracy)

        self.repo.deactivate_current_location(user_id)

        new_location = self.repo.create_location(
            user_id=user_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
            altitude=payload.altitude,
            speed=None,
            source="manual",
            is_current=True,
            is_active=True,
            metadata_notes=payload.metadata_notes,
        )

        self.repo.create_history_entry(
            user_id=user_id,
            location_id=new_location.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
            altitude=payload.altitude,
            speed=None,
            source="manual",
        )

        self.db.commit()
        self.db.refresh(new_location)
        return new_location

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_current_location(self, user_id: int) -> UserLocation:
        location = self.repo.get_current_location(user_id)
        if not location:
            raise LocationNotFoundError()
        return location

    def get_latest_location(self, user_id: int) -> UserLocation:
        location = self.repo.get_latest_location(user_id)
        if not location:
            raise LocationNotFoundError()
        return location

    def get_location_history(self, user_id: int, page: int, page_size: int):
        return self.repo.get_history(user_id, page, page_size)

    # ------------------------------------------------------------------
    # Soft Delete
    # ------------------------------------------------------------------

    def deactivate_current_location(self, user_id: int) -> bool:
        found = self.repo.soft_delete_current(user_id)
        if found:
            self.db.commit()
        return found
