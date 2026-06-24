from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class AIChatMessageSchema(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    token_count: Optional[int] = None
    model_used: Optional[str] = None

    class Config:
        from_attributes = True


class AIChatResponse(BaseModel):
    success: bool = True
    session_id: str  # UUID v4 string (was int)
    answer: str
    is_new_session: bool = False
    title: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIChatStartRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)

    # Optional session ID. Omit, null, or empty to start a new session.
    # Provide a valid UUID v4 string to continue an existing session.
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "UUID v4 session ID to continue an existing chat. "
            "Omit, set to null, or pass empty string to start a new session."
        ),
    )


class AIChatSessionDetail(BaseModel):
    session_id: str  # UUID v4 string (was int)
    title: str
    created_at: datetime
    last_message_at: Optional[datetime] = None
    message_count: int
    messages: List[AIChatMessageSchema]

    class Config:
        from_attributes = True
