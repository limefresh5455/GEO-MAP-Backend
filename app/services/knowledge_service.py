import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.exceptions.places import PlaceDetailNotFoundError
from app.integrations.openai_client import OpenAIEmbeddingClient
from app.integrations.pinecone_client import PineconeClient
from app.models.place_detail import PlaceDetail
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.place_details_repository import PlaceDetailsRepository
from app.schemas.knowledge import KnowledgeChunk, KnowledgeSyncRequest, KnowledgeSyncResponse, SyncStatus

logger = logging.getLogger(__name__)
_MAX_CHUNK_CHARS = 3000
_NS_PREFIX = "place"

def _safe_str(value: Any, fallback: str = "") -> str:
    """Return str(value) or fallback if value is None/empty."""
    if value is None:
        return fallback
    s = str(value).strip()
    return s if s else fallback


def build_place_document(place: PlaceDetail) -> Dict[str, str]:
    sections: Dict[str, str] = {}

    # 1. Summary
    summary_parts = []
    if place.display_name:
        summary_parts.append(f"Place: {place.display_name}")
    if place.formatted_address:
        summary_parts.append(f"Address: {place.formatted_address}")
    if place.latitude and place.longitude:
        summary_parts.append(
            f"Coordinates: {place.latitude:.6f}, {place.longitude:.6f}"
        )
    if place.editorial_summary:
        summary_parts.append(f"About: {place.editorial_summary}")
    if summary_parts:
        sections["summary"] = "\n".join(summary_parts)

    # 2. Category
    cat_parts = []
    if place.primary_type:
        cat_parts.append(f"Primary category: {place.primary_type}")
    if place.types and isinstance(place.types, list):
        cat_parts.append(f"All categories: {', '.join(place.types)}")
    if cat_parts:
        sections["category"] = "\n".join(cat_parts)

    # 3. Opening hours
    hours_parts = []
    if place.open_now is not None:
        hours_parts.append(
            f"Currently open: {'Yes' if place.open_now else 'No'}"
        )
    # B-053 FIX: Check if opening_hours exists and is a dict before accessing
    if place.opening_hours:
        if isinstance(place.opening_hours, dict):
            weekdays = place.opening_hours.get("weekday_descriptions")
            if weekdays and isinstance(weekdays, list):
                hours_parts.append("Opening hours:")
                hours_parts.extend(f"  {line}" for line in weekdays)
    
    if hours_parts:
        sections["hours"] = "\n".join(hours_parts)

    # 4. Contact
    contact_parts = []
    if place.international_phone_number:
        contact_parts.append(
            f"International phone: {place.international_phone_number}"
        )
    if place.national_phone_number:
        contact_parts.append(f"National phone: {place.national_phone_number}")
    if place.website_uri:
        contact_parts.append(f"Website: {place.website_uri}")
    if place.google_maps_uri:
        contact_parts.append(f"Google Maps: {place.google_maps_uri}")
    if contact_parts:
        sections["contact"] = "\n".join(contact_parts)

    # 5. Ratings & status
    rating_parts = []
    if place.rating is not None:
        rating_parts.append(f"Rating: {place.rating} / 5.0")
    if place.user_rating_count is not None:
        rating_parts.append(f"Number of reviews: {place.user_rating_count}")
    if place.price_level:
        # Normalise Google's enum string: "PRICE_LEVEL_MODERATE" → "Moderate"
        label = place.price_level.replace("PRICE_LEVEL_", "").capitalize()
        rating_parts.append(f"Price level: {label}")
    if place.business_status:
        status_label = place.business_status.replace("_", " ").capitalize()
        rating_parts.append(f"Business status: {status_label}")
    if rating_parts:
        sections["ratings"] = "\n".join(rating_parts)

    # 6. Accessibility
    if place.wheelchair_accessible_entrance is not None:
        accessible = place.wheelchair_accessible_entrance
        sections["accessibility"] = (
            f"Wheelchair accessible entrance: {'Yes' if accessible else 'No'}"
        )

    # 7. Reviews
    review_parts = []
    reviews = place.reviews or []
    if isinstance(reviews, list):
        for i, review in enumerate(reviews[:5], start=1):
            if not isinstance(review, dict):
                continue
            text = review.get("text") or ""
            author = review.get("author_name") or "Anonymous"
            rating = review.get("rating")
            if text.strip():
                stars = f" ({rating}/5)" if rating is not None else ""
                snippet = text.strip()[:500]   # cap individual review length
                review_parts.append(
                    f"Review {i} by {author}{stars}:\n  {snippet}"
                )
    if review_parts:
        sections["reviews"] = "\n\n".join(review_parts)

    return sections


# Helpers
def _compute_source_version(sections: Dict[str, str]) -> str:
    """SHA-256 of the full concatenated document — used for change detection."""
    full_text = "\n\n".join(
        f"[{k}]\n{v}" for k, v in sorted(sections.items())
    )
    return hashlib.sha256(full_text.encode("utf-8")).hexdigest()


def _truncate(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> str:
    """Hard-truncate text to max_chars characters."""
    return text[:max_chars]


# Service
class KnowledgeService:
    def __init__(
        self,
        db: Session,
        openai_client: OpenAIEmbeddingClient,
        pinecone_client: PineconeClient,
    ) -> None:
        self.db = db
        self.openai_client = openai_client
        self.pinecone_client = pinecone_client
        self.repo = KnowledgeRepository(db)
        self.details_repo = PlaceDetailsRepository(db)

    # Public: main entry point
    async def sync_place_knowledge(
        self,
        place_id: str,
        request: KnowledgeSyncRequest,
    ) -> KnowledgeSyncResponse:
        logger.info(
            "Knowledge sync start — place_id: %s, force: %s",
            place_id, request.force_resync,
        )

        # Step 1 — Load place from DB
        place = self.repo.get_place_detail(place_id)
        if place is None:
            logger.warning(
                "Knowledge sync blocked — place_id %s not in DB. "
                "Call GET /api/v1/places/{place_id}/details first.",
                place_id,
            )
            raise PlaceDetailNotFoundError(place_id)

        # Step 2 — Build document sections
        sections = build_place_document(place)

        # Filter empty sections
        sections = {k: v for k, v in sections.items() if v.strip()}

        if not sections:
            logger.warning(
                "Knowledge sync: place_id %s has no content to embed", place_id
            )
            return KnowledgeSyncResponse(
                success=False,
                place_id=place_id,
                sync_status=SyncStatus.FAILED,
                message="Place has insufficient content to build a knowledge document.",
                skipped=False,
            )

        # Step 3 — Compute source version hash
        source_version = _compute_source_version(sections)

        # Step 4 — Skip check (idempotency)
        if not request.force_resync:
            existing = self.repo.get_sync_record(place_id)
            if (
                existing
                and existing.sync_status == SyncStatus.SYNCED
                and existing.source_version == source_version
            ):
                logger.info(
                    "Knowledge sync SKIPPED — place_id: %s (source_version unchanged)",
                    place_id,
                )
                return KnowledgeSyncResponse(
                    success=True,
                    place_id=place_id,
                    sync_status=SyncStatus.SYNCED,
                    message="Already synced — place data has not changed since last sync.",
                    vector_count=existing.vector_count,
                    pinecone_namespace=existing.pinecone_namespace,
                    source_version=source_version,
                    skipped=True,
                    skip_reason="source_version unchanged",
                    synced_at=existing.synced_at,
                )

        # Step 5 — Delete stale vectors from Pinecone
        await self.pinecone_client.delete_place_namespace(place_id)

        # Step 6 & 7 — Build and truncate chunk texts
        section_names = list(sections.keys())
        chunk_texts = [
            _truncate(sections[name]) for name in section_names
        ]

        # Step 8 — Embed all chunks in one batched call
        logger.info(
            "Knowledge sync — embedding %d chunks for place_id: %s",
            len(chunk_texts), place_id,
        )
        try:
            vectors_raw = await self.openai_client.embed_texts(chunk_texts)
        except Exception as exc:
            logger.error(
                "Knowledge sync embed failed for place_id %s: %s",
                place_id, exc,
            )
            self.repo.mark_failed(place_id, str(exc))
            self.db.commit()
            raise

        # Step 9 — Build Pinecone vector dicts
        namespace = f"{_NS_PREFIX}_{place_id}"
        pinecone_vectors: List[Dict[str, Any]] = []
        knowledge_chunks: List[KnowledgeChunk] = []

        for i, (section_name, text, embedding) in enumerate(
            zip(section_names, chunk_texts, vectors_raw)
        ):
            vector_id = f"{place_id}_section_{section_name}"
            metadata: Dict[str, Any] = {
                "place_id": place_id,
                "section": section_name,
                "text": text,                      # stored for retrieval in Phase 4
                "display_name": place.display_name or "",
                "formatted_address": place.formatted_address or "",
            }
            pinecone_vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": metadata,
            })
            knowledge_chunks.append(
                KnowledgeChunk(
                    chunk_id=vector_id,
                    section=section_name,
                    text=text,
                    vector_dimension=len(embedding),
                )
            )

        # Step 10 — Upsert to Pinecone
        logger.info(
            "Knowledge sync — upserting %d vectors to Pinecone namespace: %s",
            len(pinecone_vectors), namespace,
        )
        try:
            upserted_count = await self.pinecone_client.upsert_vectors(
                place_id=place_id,
                vectors=pinecone_vectors,
            )
        except Exception as exc:
            logger.error(
                "Knowledge sync Pinecone upsert failed for place_id %s: %s",
                place_id, exc,
            )
            self.repo.mark_failed(place_id, str(exc))
            self.db.commit()
            raise

        # Step 11 — Persist sync state
        self.repo.upsert_sync_record(
            place_id=place_id,
            sync_status=SyncStatus.SYNCED,
            vector_count=upserted_count,
            pinecone_namespace=namespace,
            source_version=source_version,
            error_message=None,
        )

        # Step 12 — Mark place_details.knowledge_synced = True
        self.details_repo.mark_knowledge_synced(place_id)

        # Step 13 — Commit
        self.db.commit()

        now = datetime.now(timezone.utc)
        logger.info(
            "Knowledge sync COMPLETE — place_id: %s, vectors: %d, namespace: %s",
            place_id, upserted_count, namespace,
        )

        return KnowledgeSyncResponse(
            success=True,
            place_id=place_id,
            sync_status=SyncStatus.SYNCED,
            message=f"Knowledge sync completed — {upserted_count} vectors indexed in Pinecone.",
            vector_count=upserted_count,
            pinecone_namespace=namespace,
            source_version=source_version,
            chunks=knowledge_chunks,
            skipped=False,
            synced_at=now,
        )
