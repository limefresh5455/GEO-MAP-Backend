# app/models/user.py
"""
User PostgreSQL model — local email/password authentication.

How a user gets into this table:
  1. User calls POST /api/v1/auth/signup  (full_name, email, password)
  2. Backend hashes password, pre-creates pending user in DB
  3. Backend emails a 6-digit OTP (2-minute TTL)
  4. User calls POST /api/v1/auth/verify-otp with the code
  5. Backend activates the pending user (email_verified=True) and issues JWT pair

Fields:
  id              — internal PostgreSQL PK (used as JWT sub claim)
  full_name       — provided at signup
  email           — unique, provided at signup
  hashed_password — bcrypt hash, set at account creation, never NULL for local users
  email_verified  — True after OTP verification; local users are always True
  is_active       — set to False to deactivate an account
  credits         — application-level credit balance (default 50)
  auth_provider   — "local" for all users created via OTP signup
  created_at      — when the account was created
  updated_at      — last profile update
"""

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database.base import Base


class User(Base):
    __tablename__ = "users"

    # ── Primary key ──────────────────────────────────────────────
    id = Column(Integer, primary_key=True, index=True)

    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    email_verified = Column(
        Boolean,
        default=False,
        server_default=sa.text("false"),
        nullable=False,
        comment="True after OTP verification.",
    )

    # ── Account status ────────────────────────────────────────────
    is_active = Column(
        Boolean,
        default=True,
        server_default=sa.text("true"),
        nullable=False,
        comment="Set to False to deactivate an account.",
    )

    # ── Application data ──────────────────────────────────────────
    credits = Column(
        Integer,
        default=50,
        server_default=sa.text("50"),
        nullable=False,
        comment="Credit balance. Deducted by AI chat and Place Q&A.",
    )

    # ── Timestamps ────────────────────────────────────────────────
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

    # ── Credentials ───────────────────────────────────────────────
    hashed_password = Column(
        String(255),
        nullable=False,
        comment="bcrypt hash. Set at account creation.",
    )
    auth_provider = Column(
        String(20),
        default="local",
        server_default="local",
        nullable=False,
        comment="'local' for all users.",
    )

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, email='{self.email}', "
            f"verified={self.email_verified}, "
            f"credits={self.credits}, active={self.is_active})>"
        )
