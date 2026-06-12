from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.base import Base


class PlaceDetail(Base):
    """
    Canonical PostgreSQL record for a Google place.

    This table is the source of truth for place data in the system.
    It is written once when Place Details are first fetched and upserted
    on every subsequent fetch so the record stays fresh.

    Design rules
    ------------
    - place_id is a unique natural key (Google's ID).
    - Structured scalar fields are stored as dedicated columns for
      efficient filtering and sorting.
    - Variable-depth nested data (opening_hours, reviews, photos,
      types) is stored as JSONB for flexibility without schema churn.
    - last_fetched_at tracks when Google was last called, so callers
      can decide whether a re-fetch is warranted.
    - knowledge_synced is set by Phase 3 (Knowledge Sync) — False here
      means the record has not yet been embedded into Pinecone.
    """

    __tablename__ = "place_details"

    id = Column(Integer, primary_key=True, index=True)

    # Google's stable place identifier — unique across all users
    place_id = Column(String(255), nullable=False, unique=True, index=True)

    # Core display fields
    display_name = Column(String(500), nullable=True)
    formatted_address = Column(Text, nullable=True)

    # Coordinates
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Classification
    primary_type = Column(String(100), nullable=True)
    types = Column(JSONB, nullable=True)               # List[str]

    # Contact & web
    international_phone_number = Column(String(50), nullable=True)
    national_phone_number = Column(String(50), nullable=True)
    website_uri = Column(Text, nullable=True)
    google_maps_uri = Column(Text, nullable=True)

    # Ratings
    rating = Column(Float, nullable=True)
    user_rating_count = Column(Integer, nullable=True)

    # Business status
    business_status = Column(String(50), nullable=True)   # "OPERATIONAL" etc.

    # Opening hours — stored as JSONB (weekday text + periods)
    opening_hours = Column(JSONB, nullable=True)
    open_now = Column(Boolean, nullable=True)              # snapshot at fetch time

    # Rich data — JSONB arrays
    photos = Column(JSONB, nullable=True)     # List[{name, widthPx, heightPx}]
    reviews = Column(JSONB, nullable=True)    # List[{text, rating, author, ...}]

    # Price level — Google returns an enum string
    price_level = Column(String(30), nullable=True)       # "PRICE_LEVEL_MODERATE" etc.

    # Accessibility
    wheelchair_accessible_entrance = Column(Boolean, nullable=True)

    # Editorial summary
    editorial_summary = Column(Text, nullable=True)

    # Lifecycle / sync tracking
    last_fetched_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Set to True by Phase 3 knowledge-sync after Pinecone upsert
    knowledge_synced = Column(Boolean, default=False, nullable=False)

    # Server timestamps
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
