"""
Knowledge Sync API — Phase 3.

Routes
------
POST /api/v1/places/{place_id}/knowledge-sync
    Build and index a place's knowledge document into Pinecone.

All routes require a valid Bearer token.
The place_id must already exist in place_details (call the Details API first).
"""

import logging

from fastapi import APIRouter, Depends, Path

from app.dependencies.auth import get_current_user
from app.dependencies.knowledge import get_knowledge_service
from app.models.user import User
from app.schemas.knowledge import KnowledgeSyncRequest, KnowledgeSyncResponse
from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["Knowledge Sync"])


@router.post("/{place_id}/knowledge-sync", response_model=KnowledgeSyncResponse)
async def sync_place_knowledge(
    place_id: str = Path(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Google place ID of the place to sync. "
            "The place must have been fetched via GET /api/v1/places/{place_id}/details first."
        ),
    ),
    payload: KnowledgeSyncRequest = KnowledgeSyncRequest(),
    current_user: User = Depends(get_current_user),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSyncResponse:
    """
    Build and index the knowledge document for a specific place into Pinecone.

    **Pipeline:**
    1. Load place details from PostgreSQL (must exist — call Details API first).
    2. Build a structured plain-text document with 7 semantic sections:
       `summary`, `category`, `hours`, `contact`, `ratings`, `accessibility`, `reviews`.
    3. Hash the document to detect whether data has changed since last sync.
    4. **Skip** if already synced and data is unchanged (idempotent by default).
    5. Delete stale vectors from the place's Pinecone namespace.
    6. Chunk by section — one Pinecone vector per section.
    7. Embed all chunks via OpenAI `text-embedding-3-small` (1536 dimensions).
    8. Upsert vectors into Pinecone namespace `place_{place_id}`.
    9. Persist sync state to `place_knowledge_sync` table in PostgreSQL.
    10. Mark `place_details.knowledge_synced = True`.

    **Idempotency:**
    By default (`force_resync: false`), if the place data has not changed since
    the last sync, the endpoint returns immediately with `skipped: true`.
    Set `force_resync: true` to force a full re-embed regardless.

    **Prerequisites:**
    - `GET /api/v1/places/{place_id}/details` must have been called at least once
      so the place record exists in PostgreSQL.

    **Next step after this:**
    - `POST /api/v1/places/{place_id}/question` — ask a natural language question
      answered from this indexed knowledge.

    **Required:** `Authorization: Bearer <token>`
    """
    logger.info(
        "Knowledge sync request — user_id: %s, place_id: %s, force: %s",
        current_user.id,
        place_id,
        payload.force_resync,
    )

    return await service.sync_place_knowledge(
        place_id=place_id,
        request=payload,
    )
