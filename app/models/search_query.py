from sqlalchemy import (
    Column, DateTime, Float, Index,
    Integer, String, Text,
)
from sqlalchemy.sql import func

from app.database.base import Base


class SearchQuery(Base):
    """
    Audit log of every discovery search performed by any user.

    One row per API call to /discovery/text-search, /discovery/nearby-search,
    or /discovery/search (router).  Immutable after insert — never updated.

    Columns
    -------
    id              Auto PK.
    user_id         FK-less integer (avoids a JOIN hot-path); the user who ran it.
    search_mode     "text" | "nearby" | "router"
    raw_query       Free-text string the user typed (NULL for pure nearby searches).
    resolved_mode   Actual mode chosen by the Discovery Router ("text" | "nearby").
    latitude        User location at query time (nullable for text-only searches).
    longitude       User location at query time.
    radius          Radius in metres sent by client (nullable).
    result_count    How many places Google returned.
    from_cache      Whether the response was served from Redis.
    created_at      Server-side UTC timestamp — indexed for time-range queries.
    """

    __tablename__ = "search_queries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)

    # "text" | "nearby" | "router"
    search_mode = Column(String(10), nullable=False)
    # "text" | "nearby" — what actually ran (differs from "router" mode)
    resolved_mode = Column(String(10), nullable=True)

    raw_query = Column(Text, nullable=True)            # NULL for nearby-only calls

    # User location at query time
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    radius = Column(Float, nullable=True)

    result_count = Column(Integer, nullable=True, default=0)
    from_cache = Column(String(5), nullable=False, default="false")  # "true"/"false"

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("ix_search_queries_user_created", "user_id", "created_at"),
    )
