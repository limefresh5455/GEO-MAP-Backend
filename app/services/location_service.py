"""
Location service — GPS and manual location management.

B09 FIX: Race condition on concurrent GPS updates handled via DB-level
  IntegrityError catching. A partial unique index on user_locations
  (user_id) WHERE is_current=True enforces the single-current-location
  invariant at the database level. The service catches IntegrityError and
  retries once, making concurrent pings safe.

  The migration for this index is:
  alembic/versions/  (see Phase B migration file)
"""

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
    """
    Enforces all business rules for location management.
    Delegates DB operations to LocationRepository.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = LocationRepository(db)

    # ------------------------------------------------------------------
    # GPS Update (auto from client)
    # ------------------------------------------------------------------

    def _do_gps_write(
        self, user_id: int, payload: GPSUpdateRequest
    ) -> Tuple[UserLocation, bool]:
        """
        Core write path for GPS update — extracted so it can be retried
        once on IntegrityError (B09: race condition guard).
        """
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
        """
        Core GPS update logic:
        1. Validate coordinates.
        2. Check for duplicate (within 10m Haversine threshold).
        3. Deactivate previous current location.
        4. Create new current location record.
        5. Write history entry.
        6. Commit.

        Returns (UserLocation, is_duplicate).

        B09 FIX: If two concurrent requests both pass the duplicate check and
        both try to insert is_current=True, the DB partial unique index raises
        IntegrityError on the second insert. We catch it, rollback, and retry
        once — the retry will find the winner's row as the existing location
        and detect it as a duplicate (within 10m) or create a fresh one safely.
        """
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
        """
        Manual location update:
        1. Validate coordinates.
        2. Deactivate previous current.
        3. Create new current location with source='manual'.
        4. Write history entry.
        5. Commit.
        """
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
