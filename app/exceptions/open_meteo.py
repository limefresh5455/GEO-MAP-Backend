from fastapi import HTTPException, status

class OpenMeteoError(HTTPException):
    def __init__(self, detail: str = "Open-Meteo API error"):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


class OpenMeteoAPIError(OpenMeteoError):
    def __init__(self, detail: str = "Open-Meteo API returned an error"):
        super().__init__(detail=detail)


class OpenMeteoTimeoutError(OpenMeteoError):
    def __init__(self, detail: str = "Open-Meteo request timed out"):
        super().__init__(detail=detail)
        self.status_code = status.HTTP_504_GATEWAY_TIMEOUT


class OpenMeteoRateLimitError(OpenMeteoError):
    def __init__(self, detail: str = "Open-Meteo rate limit exceeded"):
        super().__init__(detail=detail)
        self.status_code = status.HTTP_429_TOO_MANY_REQUESTS
