# app/repositories/payment_repository.py
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction, PaymentStatus

logger = logging.getLogger(__name__)


class PaymentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        amount_inr: int,
        amount_paise: int,
        credits_purchased: int,
        stripe_payment_intent_id: str,
        stripe_client_secret: str,
        amount_usd: Optional[float] = None,
        exchange_rate: Optional[float] = None,
        currency: str = "USD",
        metadata_json: Optional[str] = None,
    ) -> PaymentTransaction:
        txn = PaymentTransaction(
            user_id=user_id,
            amount_inr=amount_inr,
            amount_paise=amount_paise,
            amount_usd=amount_usd,
            exchange_rate=exchange_rate,
            credits_purchased=credits_purchased,
            stripe_payment_intent_id=stripe_payment_intent_id,
            stripe_client_secret=stripe_client_secret,
            status=PaymentStatus.PENDING,
            currency=currency,
            metadata_json=metadata_json,
        )
        self.db.add(txn)
        self.db.flush()
        logger.info(
            "Created pending transaction: id=%s user_id=%s PI=%s amount=%s credits=%s",
            txn.id, user_id, stripe_payment_intent_id, amount_inr, credits_purchased,
        )
        return txn

    def get_by_stripe_id(
        self, stripe_payment_intent_id: str
    ) -> Optional[PaymentTransaction]:
        return (
            self.db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.stripe_payment_intent_id
                == stripe_payment_intent_id
            )
            .first()
        )

    def get_by_stripe_id_for_update(
        self, stripe_payment_intent_id: str
    ) -> Optional[PaymentTransaction]:
        """
        Same as get_by_stripe_id but acquires a row-level lock (SELECT … FOR UPDATE).

        Use this inside credit_user() to prevent a double-credit race condition
        when both the /payments/confirm endpoint and the Stripe webhook arrive
        at nearly the same time.  The first caller locks the row; the second
        blocks until the first commits, then sees status=SUCCEEDED and returns
        early via the idempotency check.
        """
        return (
            self.db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.stripe_payment_intent_id
                == stripe_payment_intent_id
            )
            .with_for_update()
            .first()
        )

    def get_by_id(self, txn_id: int) -> Optional[PaymentTransaction]:
        return (
            self.db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == txn_id)
            .first()
        )

    def mark_succeeded(
        self, txn: PaymentTransaction
    ) -> PaymentTransaction:
        txn.status = PaymentStatus.SUCCEEDED
        txn.completed_at = datetime.now(timezone.utc)
        self.db.flush()
        logger.info("Transaction %s marked as SUCCEEDED", txn.id)
        return txn

    def mark_failed(self, txn: PaymentTransaction) -> PaymentTransaction:
        txn.status = PaymentStatus.FAILED
        self.db.flush()
        logger.info("Transaction %s marked as FAILED", txn.id)
        return txn

    def get_user_history(
        self, user_id: int, limit: int = 20
    ) -> List[PaymentTransaction]:
        return (
            self.db.query(PaymentTransaction)
            .filter(PaymentTransaction.user_id == user_id)
            .order_by(PaymentTransaction.created_at.desc())
            .limit(limit)
            .all()
        )
