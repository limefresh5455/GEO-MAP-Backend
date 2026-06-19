import logging
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.dependencies.auth import get_current_user
from app.dependencies.weather import get_weather_service
from app.exceptions.custom_exceptions import LocationNotFoundError
from app.models.user import User
from app.schemas.weather import (
    AirQualityResponse,
    AirQualityData,
    WeatherForecastResponse,
    WeatherForecastData,
    WeatherLocationData,
    WeatherRequest,
)
from app.services.weather_service import WeatherService
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/weather", tags=["Weather"])


def _normalize_dates(request: WeatherRequest) -> tuple[date, date]:
    today = datetime.utcnow().date()
    start_date = request.start_date or today
    end_date = request.end_date or start_date
    return start_date, end_date


def _build_location_data(raw: dict) -> WeatherLocationData:
    return WeatherLocationData(
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        elevation=raw.get("elevation"),
        timezone=raw.get("timezone"),
        utc_offset_seconds=raw.get("utc_offset_seconds"),
    )


@router.post("/forecast", response_model=WeatherForecastResponse)
async def get_weather_forecast(
    payload: WeatherRequest,
    current_user: User = Depends(get_current_user),
    service: WeatherService = Depends(get_weather_service),
):
    """Get weather forecast for the user's saved location."""
    start_date, end_date = _normalize_dates(payload)

    logger.info(
        "weather_forecast — user_id=%s start_date=%s end_date=%s",
        current_user.id,
        start_date,
        end_date,
    )

    try:
        raw_data = await service.get_forecast(
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
        )
    except LocationNotFoundError as exc:
        logger.error("weather_forecast failed — user_id=%s no saved location", current_user.id)
        raise

    location = _build_location_data(raw_data)

    return WeatherForecastResponse(
        success=True,
        message="Weather forecast retrieved successfully",
        data=WeatherForecastData(
            location=location,
            hourly=raw_data.get("hourly"),
            daily=raw_data.get("daily"),
            current_weather=raw_data.get("current_weather"),
        ),
    )


@router.post("/air-quality", response_model=AirQualityResponse)
async def get_air_quality(
    payload: WeatherRequest,
    current_user: User = Depends(get_current_user),
    service: WeatherService = Depends(get_weather_service),
):
    """Get air quality forecast for the user's saved location."""
    start_date, end_date = _normalize_dates(payload)

    logger.info(
        "air_quality — user_id=%s start_date=%s end_date=%s",
        current_user.id,
        start_date,
        end_date,
    )

    raw_data = await service.get_air_quality(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )

    location = _build_location_data(raw_data)
    return AirQualityResponse(
        success=True,
        message="Air quality data retrieved successfully",
        data=AirQualityData(
            location=location,
            hourly=raw_data.get("hourly"),
        ),
    )
