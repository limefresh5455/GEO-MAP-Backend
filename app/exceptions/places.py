from fastapi import HTTPException, status


class GooglePlacesAPIError(HTTPException):
    def __init__(self, detail: str = "Google Places API request failed"):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class GooglePlacesRateLimitError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Google Places API rate limit exceeded. Try again later.",
        )


class GooglePlacesTimeoutError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Google Places API request timed out",
        )


class RedisUnavailableError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service temporarily unavailable",
        )


class NearbySearchValidationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class UserLocationNotFoundError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "User location not found. "
                "Please update your location using the location update API before searching."
            ),
        )


class PlaceDetailNotFoundError(HTTPException):
    def __init__(self, place_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Place '{place_id}' not found.",
        )
