from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

class SyncStatus:
    PENDING = "pending"
    SYNCED  = "synced"
    FAILED  = "failed"



class KnowledgeChunk(BaseModel):
    chunk_id: str           # "{place_id}_chunk_{index}"
    section: str            # e.g. "summary", "hours", "reviews", "contact"
    text: str               # the plain-text content that was embedded
    vector_dimension: int   # length of the embedding vector (1536 for text-embedding-3-small)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class KnowledgeSyncRequest(BaseModel):
    force_resync: bool = Field(
        default=False,
        description=(
            "Force re-embedding even if the place data has not changed "
            "since the last sync. Use after manual data corrections."
        ),
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class KnowledgeSyncResponse(BaseModel):
    success: bool
    place_id: str
    sync_status: str                          # "synced" | "skipped" | "failed"
    message: str

    # Populated on a successful or skipped sync
    vector_count: Optional[int] = None        # number of vectors in Pinecone
    pinecone_namespace: Optional[str] = None  # Pinecone namespace used
    source_version: Optional[str] = None      # SHA-256 hash of the document
    chunks: Optional[List[KnowledgeChunk]] = None  # what was chunked & embedded

    # Populated when skipped (already synced, data unchanged)
    skipped: bool = False
    skip_reason: Optional[str] = None

    # Metadata
    synced_at: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
