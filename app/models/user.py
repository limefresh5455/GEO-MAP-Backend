from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database.base import Base


class User(Base):
    """
    B-060 FIX: is_active now has both ORM default=True AND server_default=True
    to match migration B29. This prevents NULL values when creating users
    via ORM or direct SQL.
    
    B-061 FIX: Added __repr__() for better debugging experience.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    # B-060 FIX: Both defaults set to True
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # B-061 FIX: Improved debugging output
    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, email='{self.email}', "
            f"is_active={self.is_active}, full_name='{self.full_name}')>"
        )
