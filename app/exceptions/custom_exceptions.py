from fastapi import HTTPException, status


class LocationNotFoundError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active location found for this user",
        )


class InvalidCoordinatesError(HTTPException):
    def __init__(self, detail: str = "Invalid coordinate values"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class DuplicateLocationError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_200_OK,
            detail="Location unchanged -- duplicate update skipped",
        )


class UnauthorizedAccessError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource",
        )


class NotFoundError(HTTPException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


class BadRequestError(HTTPException):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


class InsufficientCreditsError(HTTPException):
    def __init__(self, required: int = 5, available: int = 0):
        detail = (
            f"Not enough credits. You need {required} credits but only have {available}. "
            f"Please purchase more credits."
        )
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=detail,
        )
