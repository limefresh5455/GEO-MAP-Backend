# app/services/payment_service.py
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction, PaymentStatus
from app.models.user import User
from app.repositories.payment_repository import PaymentRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# ── Predefined credit packages ───────────────────────────────────────────────
# These are used by GET /payments/packages and by resolve_credits().

CREDIT_PACKAGES = [
    {"inr": 150, "credits": 50, "label": "Starter"},
    {"inr": 300, "credits": 110, "label": "Popular"},
    {"inr": 500, "credits": 190, "label": "Pro"},
    {"inr": 1000, "credits": 400, "label": "Ultimate"},
]


# ── Credit calculation helpers ───────────────────────────────────────────────


def calculate_credits_for_amount(amount_inr: int) -> int:
    """
    Custom amount pricing: 1 credit per ₹3, floored.

    Examples:
        ₹99  → 33 credits
        ₹98  → 32 credits
        ₹50  → 16 credits
        ₹3   → 1 credit
        ₹2   → ValueError (below minimum)
    """
    if amount_inr < 3:
        raise ValueError("Minimum amount for custom pricing is ₹3")
    return amount_inr // 3


def resolve_credits(amount_inr: int, package_type: str = "custom") -> int:
    """
    Resolve the number of credits for a given amount and package type.

    Args:
        amount_inr: Amount in INR.
        package_type: 'custom' or one of the package names ('starter', 'popular', etc.).

    Returns:
        Number of credits the user will receive.

    Raises:
        ValueError: if a named package is requested but the amount does not match
                    the package's fixed price, preventing silent mis-billing.
    """
    if package_type == "custom":
        return calculate_credits_for_amount(amount_inr)

    # Look up a fixed package by BOTH name AND amount so that mismatched
    # requests (e.g. package="starter" with amount_inr=300) are rejected
    # instead of silently returning the wrong credit count.
    for pkg in CREDIT_PACKAGES:
        if pkg["label"].lower() == package_type:
            # Package name found — now validate the amount matches exactly
            if pkg["inr"] != amount_inr:
                expected = pkg["inr"]
                raise ValueError(
                    f"Amount ₹{amount_inr} does not match the '{package_type}' package "
                    f"(expected ₹{expected}). "
                    f"Pass the correct amount or use package='custom'."
                )
            return pkg["credits"]

    # Unknown package name — fall back to custom calculation rather than
    # silently mis-labelling an unrecognised package.
    logger.warning(
        "Unknown package_type '%s' — falling back to custom credit calculation",
        package_type,
    )
    return calculate_credits_for_amount(amount_inr)


# ── Payment Service ──────────────────────────────────────────────────────────


class PaymentService:
    """Handles payment business logic and credit allocation."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.user_repo = UserRepository(db)

    def create_pending_transaction(
        self,
        *,
        user_id: int,
        amount_inr: int,
        credits: int,
        payment_intent_id: str,
        client_secret: str,
        amount_usd: Optional[float] = None,
        exchange_rate: Optional[float] = None,
        currency: str = "USD",
    ) -> PaymentTransaction:
        """Create a pending PaymentTransaction record before Stripe confirmation."""
        return self.payment_repo.create(
            user_id=user_id,
            amount_inr=amount_inr,
            amount_paise=amount_inr * 100,
            credits_purchased=credits,
            stripe_payment_intent_id=payment_intent_id,
            stripe_client_secret=client_secret,
            amount_usd=amount_usd,
            exchange_rate=exchange_rate,
            currency=currency,
        )

    def credit_user(self, payment_intent_id: str) -> Optional[User]:
        """
        Allocate credits to the user after a successful Stripe payment.

        Called by both the /payments/confirm endpoint and the /stripe/webhook
        handler.  Safe to call from both concurrently because the row-level
        lock (SELECT … FOR UPDATE) inside get_by_stripe_id_for_update() ensures
        only one caller transitions the transaction from PENDING → SUCCEEDED.

        Idempotent: if the transaction is already marked SUCCEEDED, the user is
        returned without double-crediting.

        NOTE: this method deliberately does NOT call db.commit().  Commit
        responsibility belongs to the route handler so that the full request
        can be rolled back atomically if anything fails after this call.

        Args:
            payment_intent_id: Stripe PaymentIntent ID (pi_...).

        Returns:
            The updated User, or None if the transaction or user is not found.
        """
        # Use the locked read to prevent a race condition between the confirm
        # endpoint and the Stripe webhook arriving simultaneously.
        txn = self.payment_repo.get_by_stripe_id_for_update(payment_intent_id)
        if txn is None:
            logger.error(
                "No transaction found for PaymentIntent: %s", payment_intent_id
            )
            return None

        # Idempotency check — already processed (second caller sees this after
        # the first caller commits and releases the row lock).
        if txn.status == PaymentStatus.SUCCEEDED:
            logger.warning(
                "Duplicate credit attempt — PI %s already succeeded, returning user without re-crediting",
                payment_intent_id,
            )
            return self.user_repo.get_by_id(txn.user_id)

        # Mark transaction as succeeded (flush only — caller commits)
        txn = self.payment_repo.mark_succeeded(txn)

        # Credit the user
        user = self.user_repo.get_by_id(txn.user_id)
        if user is None:
            # Roll back the mark_succeeded flush so the transaction stays PENDING.
            # The caller owns no commit yet, so expunge is safe here.
            # The next webhook retry or /confirm call will attempt again.
            self.db.expunge(txn)
            self.db.rollback()
            logger.error(
                "User %s not found for PI %s — rolled back mark_succeeded, "
                "transaction %s remains PENDING for retry",
                txn.user_id,
                payment_intent_id,
                txn.id,
            )
            return None

        user.credits = (user.credits or 0) + txn.credits_purchased
        # flush makes the new balance visible within this transaction but does
        # NOT commit — the route handler owns the commit boundary.
        self.db.flush()

        logger.info(
            "Credited %s credits to user %s (new balance: %s) — awaiting caller commit",
            txn.credits_purchased,
            user.id,
            user.credits,
        )
        return user
