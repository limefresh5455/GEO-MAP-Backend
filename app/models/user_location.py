from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base import Base


class UserLocation(Base):

    __tablename__ = "user_locations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Coordinates
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Optional GPS metadata
    accuracy = Column(Float, nullable=True)  # metres
    altitude = Column(Float, nullable=True)  # metres above sea level
    speed = Column(Float, nullable=True)  # metres/second

    # Source of update: 'gps' or 'manual'
    source = Column(String(10), nullable=False, default="gps")

    # State flags
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Client-side GPS timestamp (optional)
    client_timestamp = Column(DateTime(timezone=True), nullable=True)

    # Server timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Optional metadata (device info, notes, etc.)
    metadata_notes = Column(Text, nullable=True)

    # Relationships
    history_entries = relationship(
        "LocationHistory",
        back_populates="location_record",
    )
