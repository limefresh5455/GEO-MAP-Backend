import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_token_sub(sub: Optional[str]) -> Optional[int]:
    if not sub:
        return None
    try:
        return int(sub)
    except (ValueError, TypeError):
        return None


def strip_bearer_prefix(raw_token: str) -> str:
    prefix = "Bearer "
    if raw_token[: len(prefix)].lower() == prefix.lower():
        return raw_token[len(prefix) :].strip()
    return raw_token.strip()
