# app/models/payment_transaction.py
import enum
import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, Enum as SAEnum
from sqlalchemy.sql import func

from app.database.base import Base
from app.models.user import User


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        sa.ForeignKey(User.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Stripe fields
    stripe_payment_intent_id = Column(
        String(255), unique=True, nullable=False, index=True
    )
    stripe_client_secret = Column(String(255), nullable=True)

    # Amount & credits
    amount_inr = Column(Integer, nullable=False, comment="Amount in INR (e.g. 150)")
    amount_paise = Column(
        Integer,
        nullable=False,
        comment="Amount in paise (e.g. 15000 for ₹150)",
    )
    amount_usd = Column(
        Float,
        nullable=True,
        comment="Converted amount in USD at time of payment (e.g. 1.80)",
    )
    exchange_rate = Column(
        Float,
        nullable=True,
        comment="INR per 1 USD at time of payment (e.g. 83.52)",
    )
    credits_purchased = Column(Integer, nullable=False)

    # Currency of the Stripe charge
    currency = Column(
        String(3),
        default="USD",
        nullable=False,
        comment="3-letter ISO currency code of the Stripe charge (always USD)",
    )

    # Status
    status = Column(
        SAEnum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Extra metadata as JSON string
    metadata_json = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PaymentTransaction(id={self.id}, user_id={self.user_id}, "
            f"amount_inr={self.amount_inr}, credits={self.credits_purchased}, "
            f"status='{self.status}', pi='{self.stripe_payment_intent_id}')>"
        )
