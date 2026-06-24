from datetime import date
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class WeatherRequest(BaseModel):
    start_date: Optional[date] = Field(
        None,
        description="Start date for forecast/air quality data in YYYY-MM-DD format.",
    )
    end_date: Optional[date] = Field(
        None,
        description="End date for forecast/air quality data in YYYY-MM-DD format.",
    )

    @field_validator("end_date")
    @classmethod
    def validate_end_date(cls, value: Optional[date], info):
        start_date = info.data.get("start_date")
        if value is not None and start_date is not None and value < start_date:
            raise ValueError("end_date cannot be before start_date")
        return value


class WeatherLocationData(BaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float]
    timezone: Optional[str]
    utc_offset_seconds: Optional[int]


class WeatherForecastData(BaseModel):
    location: WeatherLocationData
    hourly: Optional[Dict[str, Any]] = None
    daily: Optional[Dict[str, Any]] = None
    current_weather: Optional[Dict[str, Any]] = None


class WeatherForecastResponse(BaseModel):
    success: bool
    message: str
    data: Optional[WeatherForecastData] = None


class AirQualityData(BaseModel):
    location: WeatherLocationData
    hourly: Optional[Dict[str, Any]] = None


class AirQualityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[AirQualityData] = None
