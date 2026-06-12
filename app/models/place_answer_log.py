from sqlalchemy import (
    Column, DateTime, Float, ForeignKey,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.base import Base


class PlaceAnswerLog(Base):
    """
    Immutable record of every answer generated for a place question.

    One row per answer (one-to-one with PlaceQuestion in normal flow).
    Stores the full context package sent to OpenAI so answers can be
    audited, replayed, and used for fine-tuning.

    Columns
    -------
    id                  Auto PK.
    question_id         FK → place_questions.id (CASCADE delete).
    user_id             Denormalised for direct user-scoped queries.
    place_id            Denormalised for direct place-scoped queries.
    answer_text         The final answer returned to the user.
    confidence_score    Float 0.0–1.0 computed from Pinecone match scores.
    answer_source       "rag" | "structured_only" | "fallback"
    grounding_chunks    JSONB array — the Pinecone chunk texts used as context.
    context_tokens      Approximate token count of the context sent to OpenAI.
    model_used          OpenAI model name (e.g. "gpt-4o-mini").
    latency_ms          End-to-end answer generation time in milliseconds.
    created_at          UTC timestamp.
    """

    __tablename__ = "place_answer_logs"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(
        Integer,
        ForeignKey("place_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, nullable=False, index=True)
    place_id = Column(String(255), nullable=False, index=True)

    # Answer content
    answer_text = Column(Text, nullable=False)

    # Confidence — derived from Pinecone cosine similarity scores
    confidence_score = Column(Float, nullable=True)

    # "rag" = answered from Pinecone + structured data
    # "structured_only" = answered from PG only (no Pinecone match)
    # "fallback" = no knowledge indexed, answered from place name/address only
    answer_source = Column(String(20), nullable=False, default="rag")

    # Supporting evidence sent to OpenAI
    grounding_chunks = Column(JSONB, nullable=True)  # List[{section, text, score}]
    context_tokens = Column(Integer, nullable=True)

    # Generation metadata
    model_used = Column(String(100), nullable=True)
    latency_ms = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
