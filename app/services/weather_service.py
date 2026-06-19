import logging
from datetime import date
from typing import Dict
from sqlalchemy.orm import Session
from app.exceptions.custom_exceptions import LocationNotFoundError
from app.integrations.open_meteo import OpenMeteoClient
from app.models.user_location import UserLocation
from app.repositories.location_repository import LocationRepository

logger = logging.getLogger(__name__)


class WeatherService:
    def __init__(
        self,
        db: Session,
        open_meteo_client: OpenMeteoClient,
    ) -> None:
        self._db = db
        self._location_repo = LocationRepository(db)
        self._open_meteo_client = open_meteo_client

    def _get_location(self, user_id: int) -> UserLocation:
        location = self._location_repo.get_current_location(user_id)
        if not location:
            raise LocationNotFoundError(
                "No active location found for this user. POST /api/v1/locations/gps first."
            )
        return location

    async def get_forecast(
        self,
        user_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict:
        location = self._get_location(user_id)
        return await self._open_meteo_client.get_forecast(
            latitude=location.latitude,
            longitude=location.longitude,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

    async def get_air_quality(
        self,
        user_id: int,
        start_date: date,
        end_date: date,
    ) -> Dict:
        location = self._get_location(user_id)
        return await self._open_meteo_client.get_air_quality(
            latitude=location.latitude,
            longitude=location.longitude,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
