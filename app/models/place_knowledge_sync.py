from sqlalchemy import (
    Boolean, Column, DateTime, Integer,
    String, Text,
)
from sqlalchemy.sql import func

from app.database.base import Base


class PlaceKnowledgeSync(Base):
    """
    Tracks the Pinecone embedding sync state for each place.

    One row per place_id. Updated in place on every sync run — this is
    NOT an append-only audit table; it represents current sync state.

    Columns
    -------
    id                  Auto PK.
    place_id            Google place ID (matches place_details.place_id).
                        Unique — one sync record per place.
    sync_status         "pending" | "synced" | "failed"
    vector_count        Number of vectors upserted in the last sync run.
    pinecone_namespace  Pinecone namespace used for this place's vectors.
    source_version      Hash or timestamp of the place_details row that was
                        embedded — lets us detect staleness without re-reading
                        the full record.
    error_message       Last error text if sync_status == "failed".
    synced_at           UTC timestamp of the last successful sync.
    created_at          Row creation timestamp.
    updated_at          Last modification timestamp.
    """

    __tablename__ = "place_knowledge_sync"

    id = Column(Integer, primary_key=True, index=True)

    # Natural key — one record per place
    place_id = Column(String(255), nullable=False, unique=True, index=True)

    # "pending" | "synced" | "failed"
    sync_status = Column(String(10), nullable=False, default="pending", index=True)

    # How many Pinecone vectors were written in the last successful sync
    vector_count = Column(Integer, nullable=True, default=0)

    # Pinecone namespace used (format: "place_{place_id}")
    pinecone_namespace = Column(String(300), nullable=True)

    # SHA-256 of the canonical document at the time of the last sync.
    # Stored so we can skip re-embedding when nothing has changed.
    source_version = Column(String(64), nullable=True)

    # Last failure detail
    error_message = Column(Text, nullable=True)

    # Timestamps
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
