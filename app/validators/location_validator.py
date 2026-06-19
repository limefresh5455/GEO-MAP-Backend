import math
from typing import Optional
from app.exceptions.custom_exceptions import InvalidCoordinatesError

DUPLICATE_DISTANCE_THRESHOLD_METERS = 10.0

def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise InvalidCoordinatesError(
            f"Latitude must be between -90 and 90. Received: {latitude}"
        )
    if not (-180.0 <= longitude <= 180.0):
        raise InvalidCoordinatesError(
            f"Longitude must be between -180 and 180. Received: {longitude}"
        )


def validate_accuracy(accuracy: Optional[float]) -> None:
    if accuracy is not None and accuracy < 0:
        raise InvalidCoordinatesError("Accuracy must be a non-negative value")


def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_duplicate_location(
    new_lat: float,
    new_lon: float,
    existing_lat: float,
    existing_lon: float,
    threshold_meters: float = DUPLICATE_DISTANCE_THRESHOLD_METERS,
) -> bool:
    distance = haversine_distance(new_lat, new_lon, existing_lat, existing_lon)
    return distance < threshold_meters
