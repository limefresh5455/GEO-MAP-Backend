from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database.base import Base


class PlaceDetail(Base):

    __tablename__ = "place_details"

    id = Column(Integer, primary_key=True, index=True)
    place_id = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(500), nullable=True)
    formatted_address = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    primary_type = Column(String(100), nullable=True)
    types = Column(JSONB, nullable=True)               # List[str]
    international_phone_number = Column(String(50), nullable=True)
    national_phone_number = Column(String(50), nullable=True)
    website_uri = Column(Text, nullable=True)
    google_maps_uri = Column(Text, nullable=True)
    rating = Column(Float, nullable=True)
    user_rating_count = Column(Integer, nullable=True)
    business_status = Column(String(50), nullable=True)   # "OPERATIONAL" etc.
    opening_hours = Column(JSONB, nullable=True)
    open_now = Column(Boolean, nullable=True)              # snapshot at fetch time
    photos = Column(JSONB, nullable=True)     # List[{name, widthPx, heightPx}]
    reviews = Column(JSONB, nullable=True)    # List[{text, rating, author, ...}]
    price_level = Column(String(30), nullable=True)       # "PRICE_LEVEL_MODERATE" etc.
    wheelchair_accessible_entrance = Column(Boolean, nullable=True)
    editorial_summary = Column(Text, nullable=True)
    last_fetched_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    knowledge_synced = Column(Boolean, default=False, nullable=False)
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
