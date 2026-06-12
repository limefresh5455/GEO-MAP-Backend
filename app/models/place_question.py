from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    Integer, String, Text,
)
from sqlalchemy.sql import func

from app.database.base import Base


class PlaceQuestion(Base):
    """
    Immutable log of every question asked about a specific place.

    One row per question submission.  Never updated after insert.
    Provides an audit trail and enables analytics like:
    - "most asked questions per place"
    - "unanswered or low-confidence questions"
    - "questions that hit fallback (no knowledge synced)"

    Columns
    -------
    id                  Auto PK.
    user_id             FK-less integer (avoids hot-path JOIN).
    place_id            Google place ID the question is about.
    question_text       Raw user question string.
    knowledge_available Whether the place had a Pinecone namespace at
                        question time (True = RAG path, False = fallback).
    pinecone_matches    Number of Pinecone chunks retrieved.
    created_at          UTC timestamp — indexed for time-range queries.
    """

    __tablename__ = "place_questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    place_id = Column(String(255), nullable=False, index=True)
    question_text = Column(Text, nullable=False)

    # Context quality signals
    knowledge_available = Column(Boolean, nullable=False, default=False)
    pinecone_matches = Column(Integer, nullable=True, default=0)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
