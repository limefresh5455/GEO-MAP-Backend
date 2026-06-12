from sqlalchemy import (
    Column, DateTime, Float, ForeignKey,
    Integer, String, Text,
)
from sqlalchemy.sql import func

from app.database.base import Base


class SearchResult(Base):
    """
    Snapshot of each place returned in a search response.

    One row per place per search query.  Immutable after insert.
    Provides a local record of what Google returned without having to
    call the Details API immediately, and powers analytics queries like
    "which places appear most often in searches near location X".

    Columns
    -------
    id                  Auto PK.
    query_id            FK → search_queries.id (CASCADE delete).
    user_id             Denormalised for direct user-scoped queries.
    place_id            Google place ID (e.g. "ChIJ…").
    display_name        Place name as returned by Google.
    formatted_address   Full address string.
    primary_type        Google primary place type (e.g. "restaurant").
    latitude            Place coordinates.
    longitude
    rating              Google rating (0–5).
    user_rating_count   Number of Google reviews.
    business_status     "OPERATIONAL" | "CLOSED_TEMPORARILY" | etc.
    rank_position       Zero-based position in the result list (0 = first result).
    created_at          Server-side UTC timestamp.
    """

    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True, index=True)
    query_id = Column(
        Integer,
        ForeignKey("search_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, nullable=False, index=True)

    place_id = Column(String(255), nullable=False, index=True)
    display_name = Column(String(500), nullable=True)
    formatted_address = Column(Text, nullable=True)
    primary_type = Column(String(100), nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    rating = Column(Float, nullable=True)
    user_rating_count = Column(Integer, nullable=True)
    business_status = Column(String(50), nullable=True)

    rank_position = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
