"""
Pydantic schemas for the Knowledge Sync layer.

Covers:
  POST /api/v1/places/{place_id}/knowledge-sync
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sync status constants — mirrors PlaceKnowledgeSync.sync_status column
# ---------------------------------------------------------------------------

class SyncStatus:
    PENDING = "pending"
    SYNCED  = "synced"
    FAILED  = "failed"


# ---------------------------------------------------------------------------
# Document chunk — internal use; exposed in response for transparency
# ---------------------------------------------------------------------------

class KnowledgeChunk(BaseModel):
    """
    A single semantic chunk of the place document that was embedded.
    Returned in the sync response so callers can see what was indexed.
    """
    chunk_id: str           # "{place_id}_chunk_{index}"
    section: str            # e.g. "summary", "hours", "reviews", "contact"
    text: str               # the plain-text content that was embedded
    vector_dimension: int   # length of the embedding vector (1536 for text-embedding-3-small)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class KnowledgeSyncRequest(BaseModel):
    """
    Optional request body for POST /api/v1/places/{place_id}/knowledge-sync.

    force_resync: When True, re-embeds and upserts even if the stored
                  source_version hash matches the current place data.
                  Defaults to False — idempotent by default.
    """
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
    """Standard response envelope for POST /api/v1/places/{place_id}/knowledge-sync."""

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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
