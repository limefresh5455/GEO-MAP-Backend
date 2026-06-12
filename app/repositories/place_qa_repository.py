"""
PlaceQARepository — PostgreSQL operations for place_questions and place_answer_logs.

Rules
-----
- Both tables are append-only (immutable audit log).
- Never commits — the service owns the transaction boundary.
- Writes are flushed so IDs are available before commit.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.place_answer_log import PlaceAnswerLog
from app.models.place_question import PlaceQuestion

logger = logging.getLogger(__name__)


class PlaceQARepository:
    """
    Handles inserts and reads for place_questions and place_answer_logs.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_question(
        self,
        *,
        user_id: int,
        place_id: str,
        question_text: str,
        knowledge_available: bool,
        pinecone_matches: int,
    ) -> PlaceQuestion:
        """
        Insert an audit row for the question submission.
        Flushed (not committed) so .id is available for the answer log FK.
        """
        record = PlaceQuestion(
            user_id=user_id,
            place_id=place_id,
            question_text=question_text,
            knowledge_available=knowledge_available,
            pinecone_matches=pinecone_matches,
        )
        self.db.add(record)
        self.db.flush()
        logger.debug(
            "PlaceQuestion flushed: id=%s user=%s place=%s knowledge=%s",
            record.id, user_id, place_id, knowledge_available,
        )
        return record

    def create_answer_log(
        self,
        *,
        question_id: int,
        user_id: int,
        place_id: str,
        answer_text: str,
        confidence_score: Optional[float],
        answer_source: str,
        grounding_chunks: Optional[List[Dict[str, Any]]],
        context_tokens: Optional[int],
        model_used: str,
        latency_ms: Optional[int],
    ) -> PlaceAnswerLog:
        """
        Insert the answer audit record.
        Flushed (not committed) — caller commits when ready.
        """
        record = PlaceAnswerLog(
            question_id=question_id,
            user_id=user_id,
            place_id=place_id,
            answer_text=answer_text,
            confidence_score=confidence_score,
            answer_source=answer_source,
            grounding_chunks=grounding_chunks,
            context_tokens=context_tokens,
            model_used=model_used,
            latency_ms=latency_ms,
        )
        self.db.add(record)
        self.db.flush()
        logger.debug(
            "PlaceAnswerLog flushed: question_id=%s source=%s confidence=%s",
            question_id, answer_source, confidence_score,
        )
        return record

    # ------------------------------------------------------------------
    # Reads (analytics)
    # ------------------------------------------------------------------

    def get_recent_questions_for_place(
        self, place_id: str, limit: int = 10
    ) -> List[PlaceQuestion]:
        """Return the N most recent questions for a specific place."""
        return (
            self.db.query(PlaceQuestion)
            .filter(PlaceQuestion.place_id == place_id)
            .order_by(PlaceQuestion.created_at.desc())
            .limit(limit)
            .all()
        )
