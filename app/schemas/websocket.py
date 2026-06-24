from typing import Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Client → Server messages
# ---------------------------------------------------------------------------


class WSClientMessage(BaseModel):
    type: str = Field(
        ...,
        description="Message type: 'chat_message' | 'place_question'",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User's message or question",
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "UUID v4 session ID to continue an existing conversation. "
            "Omit, null, or empty to start a new session."
        ),
    )
    place_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Required for type='place_question' — the Google Place ID",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of knowledge chunks to retrieve (place_question only)",
    )


# ---------------------------------------------------------------------------
# Server → Client message types
# ---------------------------------------------------------------------------


class WSStreamStart(BaseModel):
    """Sent when streaming begins."""

    type: str = "stream_start"
    session_id: str
    is_new_session: bool


class WSChunk(BaseModel):
    """A single token/chunk of the streaming response."""

    type: str = "chunk"
    session_id: str
    token: str


class WSStreamEnd(BaseModel):
    """Sent when streaming completes successfully."""

    type: str = "stream_end"
    session_id: str
    title: Optional[str] = None


class WSError(BaseModel):
    """Sent when an error occurs during streaming."""

    type: str = "error"
    session_id: Optional[str] = None
    message: str


class WSConnectionAck(BaseModel):
    """Sent immediately after WebSocket handshake."""

    type: str = "connected"
    message: str = "Connected to Geo Map streaming server"
