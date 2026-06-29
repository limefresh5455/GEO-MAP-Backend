from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from app.utils.session_id import validate_uuid4


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
    session_id: str
    answer: str
    is_new_session: bool = False
    title: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIChatStartRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "UUID v4 session ID to continue an existing chat. "
            "Omit, set to null, or pass empty string to start a new session."
        ),
    )

    @field_validator("session_id", mode="before")
    @classmethod
    def validate_session_id(cls, v):
        return validate_uuid4(v)


class AIChatSessionDetail(BaseModel):
    session_id: str
    title: str
    created_at: datetime
    last_message_at: Optional[datetime] = None
    message_count: int
    messages: List[AIChatMessageSchema]

    class Config:
        from_attributes = True
