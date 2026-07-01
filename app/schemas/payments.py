# app/schemas/payments.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _reject_float_int(value, field_name: str):
    """
    Reject float values for an integer field to prevent silent truncation.
    
    Pydantic v2 silently coerces floats to ints (e.g. 150.5 → 150), which
    causes silent data loss in monetary amounts and counts. This validator
    raises a clear error instead.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{field_name} must be a whole number (integer). "
            f"Decimal values are not supported — please use a whole number "
            f"like {int(value)} or {int(value) + 1}."
        )
    return value


# Pricing packages 


class PaymentPackage(BaseModel):
    inr: int
    credits: int
    label: str
    currency: str = "INR"
        


class PackagesResponse(BaseModel):
    success: bool = True
    packages: List[PaymentPackage]
    custom_pricing: dict


# ── Create PaymentIntent ─────────────────────────────────────────────────────


class CreatePaymentIntentRequest(BaseModel):
    amount_inr: int = Field(
        ..., ge=3, description="Amount in INR (minimum ₹3)"
    )
    package: str = Field(
        default="custom",
        pattern=r"^(custom|starter|popular|pro|ultimate)$",
        description="Use 'custom' for custom amount, or a package name for fixed pricing",
    )

    @field_validator("amount_inr", mode="before")
    @classmethod
    def reject_float_amount_inr(cls, v):
        """Reject float values that would silently truncate."""
        return _reject_float_int(v, "amount_inr")

    @field_validator("package", mode="before")
    @classmethod
    def normalize_package(cls, v: str) -> str:
        """Lowercase the package name before pattern validation."""
        if isinstance(v, str):
            return v.lower()
        return v


class CreatePaymentIntentResponse(BaseModel):
    success: bool = True
    client_secret: str
    payment_intent_id: str
    credits_to_receive: int
    amount_inr: int
    amount_usd: float = Field(..., description="Converted amount charged to card in USD")
    exchange_rate: float = Field(..., description="INR per 1 USD used for this conversion")
    currency: str = Field(default="USD", description="Currency the Stripe charge was made in (always USD)")
    plan_currency: str = Field(default="INR", description="Currency of the selected pricing plan")
    


# ── Payment History ──────────────────────────────────────────────────────────


class PaymentHistoryItem(BaseModel):
    id: int
    amount_inr: int
    amount_usd: Optional[float] = None
    exchange_rate: Optional[float] = None
    credits_purchased: int
    status: str
    currency: str = Field(default="USD", description="Currency the Stripe charge was made in")
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaymentHistoryResponse(BaseModel):
    success: bool = True
    transactions: List[PaymentHistoryItem]


# ── Stripe Webhook ───────────────────────────────────────────────────────────


class ConfirmPaymentRequest(BaseModel):
    payment_intent_id: str = Field(..., description="Stripe PaymentIntent ID (pi_...)")


class ConfirmPaymentResponse(BaseModel):
    success: bool = True
    credits_added: int
    new_balance: int
    status: str


class StripeConfigResponse(BaseModel):
    publishable_key: str


class StripeWebhookResponse(BaseModel):
    received: bool = True
