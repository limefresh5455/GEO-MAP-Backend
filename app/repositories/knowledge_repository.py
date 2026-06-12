"""
KnowledgeRepository — PostgreSQL operations for the place_knowledge_sync table.

Rules
-----
- Upsert semantics: one row per place_id, updated in place.
- Never commits — the service owns the transaction boundary.
- Also provides read access to place_details so the knowledge service
  does not need to import PlaceDetailsRepository directly.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.place_detail import PlaceDetail
from app.models.place_knowledge_sync import PlaceKnowledgeSync

logger = logging.getLogger(__name__)


class KnowledgeRepository:
    """
    Handles sync-state tracking in place_knowledge_sync
    and read-only access to place_details.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # place_details reads (read-only — writes owned by PlaceDetailsRepository)
    # ------------------------------------------------------------------

    def get_place_detail(self, place_id: str) -> Optional[PlaceDetail]:
        """Return the canonical place record, or None if not yet fetched."""
        return (
            self.db.query(PlaceDetail)
            .filter(PlaceDetail.place_id == place_id)
            .first()
        )

    # ------------------------------------------------------------------
    # place_knowledge_sync reads
    # ------------------------------------------------------------------

    def get_sync_record(self, place_id: str) -> Optional[PlaceKnowledgeSync]:
        """Return the sync state record for a place, or None if not yet synced."""
        return (
            self.db.query(PlaceKnowledgeSync)
            .filter(PlaceKnowledgeSync.place_id == place_id)
            .first()
        )

    # ------------------------------------------------------------------
    # place_knowledge_sync writes
    # ------------------------------------------------------------------

    def upsert_sync_record(
        self,
        *,
        place_id: str,
        sync_status: str,
        vector_count: int,
        pinecone_namespace: str,
        source_version: str,
        error_message: Optional[str] = None,
    ) -> PlaceKnowledgeSync:
        """
        Insert or update the sync state for a place.

        On success:  sync_status="synced",  synced_at=now,  error_message=None
        On failure:  sync_status="failed",  error_message=<detail>,  synced_at unchanged

        Flushed (not committed) — caller commits.
        """
        existing = self.get_sync_record(place_id)
        now = datetime.now(timezone.utc)

        if existing:
            existing.sync_status = sync_status
            existing.vector_count = vector_count
            existing.pinecone_namespace = pinecone_namespace
            existing.source_version = source_version
            existing.error_message = error_message
            if sync_status == "synced":
                existing.synced_at = now
            self.db.flush()
            logger.debug(
                "PlaceKnowledgeSync updated: place_id=%s status=%s vectors=%d",
                place_id, sync_status, vector_count,
            )
            return existing

        record = PlaceKnowledgeSync(
            place_id=place_id,
            sync_status=sync_status,
            vector_count=vector_count,
            pinecone_namespace=pinecone_namespace,
            source_version=source_version,
            error_message=error_message,
            synced_at=now if sync_status == "synced" else None,
        )
        self.db.add(record)
        self.db.flush()
        logger.debug(
            "PlaceKnowledgeSync inserted: place_id=%s status=%s vectors=%d",
            place_id, sync_status, vector_count,
        )
        return record

    def mark_failed(self, place_id: str, error_message: str) -> None:
        """
        Mark a sync as failed without changing vector_count or synced_at.
        Safe to call even if no sync record exists yet.
        """
        existing = self.get_sync_record(place_id)
        if existing:
            existing.sync_status = "failed"
            existing.error_message = error_message
            self.db.flush()
        else:
            record = PlaceKnowledgeSync(
                place_id=place_id,
                sync_status="failed",
                vector_count=0,
                error_message=error_message,
            )
            self.db.add(record)
            self.db.flush()
