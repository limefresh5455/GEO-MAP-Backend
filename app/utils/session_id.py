import uuid
from typing import Any, Optional

# Pydantic v2 validator that can be used as @field_validator on any str field
# that should contain a UUID v4.
_UUID_V4_HELP = (
    "Expected a valid UUID v4 string (e.g. " "'3f2a1b4c-8e9d-4a2b-b1c3-d4e5f6a7b8c9')."
)


def generate_session_id() -> str:
    return str(uuid.uuid4())


def validate_uuid4(value: Any) -> Optional[str]:
    """
    Validate that the given value is a valid UUID (v4) string.
    Returns the normalized string, or raises ValueError.
    Can be used as a Pydantic @field_validator or standalone.

    Accepts None/empty → returns None (so it can be used on Optional[str] fields).
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        uuid_obj = uuid.UUID(str(value))
        # Ensure it's v4 specifically (UUID version 4)
        if uuid_obj.version != 4:
            raise ValueError(f"UUID must be version 4. {_UUID_V4_HELP}")
        return str(uuid_obj)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid session ID format. {_UUID_V4_HELP}")


def validate_uuid4_required(value: str) -> str:
    """
    Like validate_uuid4 but rejects None/empty values (for required fields).
    """
    result = validate_uuid4(value)
    if result is None:
        raise ValueError(f"A valid session ID is required. {_UUID_V4_HELP}")
    return result
