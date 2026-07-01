# app/services/stripe_service.py
import logging
from typing import Any, Dict, Optional

import stripe
from stripe import StripeError

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Stripe initialisation with key validation ────────────────────────────────


def _validate_stripe_key() -> None:
    """
    Validate that the configured STRIPE_SECRET_KEY looks like a Stripe secret key.

    Stripe secret keys start with ``sk_test_`` or ``sk_live_``, while publishable
    keys start with ``pk_test_`` or ``pk_live_``.  Using a publishable key for
    server-side API calls will always fail with a PermissionError.

    This check runs once at import time so the developer gets a clear, immediate
    error message rather than a cryptic Stripe API error at runtime.
    """
    key = settings.STRIPE_SECRET_KEY or ""
    if not key:
        logger.warning(
            "STRIPE_SECRET_KEY is not set — payment endpoints will fail at runtime."
        )
        return

    if key.startswith("pk_"):
        raise ValueError(
            "STRIPE_SECRET_KEY appears to be a publishable key (starts with 'pk_').\n"
            "Publishable keys can only be used on the frontend (e.g. Stripe.js).\n"
            "Please set STRIPE_SECRET_KEY to a secret key (starts with 'sk_test_' "
            "or 'sk_live_').\n"
            "You can find your API keys at: https://dashboard.stripe.com/apikeys"
        )

    if not key.startswith(("sk_test_", "sk_live_")):
        logger.warning(
            "STRIPE_SECRET_KEY does not start with 'sk_test_' or 'sk_live_'.  "
            "This may still work if you are using a restricted key, but double-check "
            "that you are using the correct key from the Stripe Dashboard."
        )


_validate_stripe_key()
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    """Thin wrapper around Stripe API for payment processing."""

    @staticmethod
    async def create_payment_intent(
        amount_paise: int,
        currency: str = "usd",
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe PaymentIntent.

        Args:
            amount_paise: Amount in smallest currency unit.
                          For USD: cents (e.g. 180 for $1.80).
            currency: 3-letter ISO currency code (default 'usd').
            metadata: Optional dict of up to 50 key/value pairs (values must be strings).

        Returns:
            Dict with keys: id, client_secret, amount, currency.

        Raises:
            stripe.error.StripeError: on any Stripe API error.
        """
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_paise,
                currency=currency,
                metadata=metadata or {},
                automatic_payment_methods={
                    "enabled": True,
                    "allow_redirects": "never",   # allows CLI + direct card confirm without return_url
                },
            )
            logger.info(
                "Stripe PaymentIntent created: %s (amount=%s %s, metadata=%s)",
                intent.id,
                amount_paise,
                currency,
                metadata,
            )
            return {
                "id": intent.id,
                "client_secret": intent.client_secret,
                "amount": intent.amount,
                "currency": intent.currency,
            }
        except StripeError as exc:
            logger.error("Stripe error creating PaymentIntent: %s", exc)
            raise

    @staticmethod
    async def retrieve_payment_intent(
        payment_intent_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve a PaymentIntent from Stripe to verify its status.

        Used by the /payments/confirm endpoint after the frontend
        confirms payment with Stripe.js.

        Args:
            payment_intent_id: The Stripe PaymentIntent ID (pi_...).

        Returns:
            Dict with keys: id, status, amount, currency, metadata.

        Raises:
            stripe.error.StripeError: if the PI cannot be retrieved.
        """
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            logger.info(
                "Stripe PaymentIntent retrieved: %s (status=%s)",
                intent.id,
                intent.status,
            )
            return {
                "id": intent.id,
                "status": intent.status,
                "amount": intent.amount,
                "currency": intent.currency,
            }
        except StripeError as exc:
            logger.error("Stripe error retrieving PaymentIntent: %s", exc)
            raise

    @staticmethod
    async def construct_webhook_event(
        payload: bytes,
        sig_header: str,
        webhook_secret: str,
    ) -> Any:
        """
        Verify and construct a Stripe webhook event from the raw request body.

        Uses stripe.WebhookSignature.verify_header for signature verification
        (which works correctly in v15), then parses the JSON directly to
        avoid Event._construct_from issues in Stripe Python v15.

        Args:
            payload: Raw request body as bytes.
            sig_header: Value of the 'stripe-signature' header.
            webhook_secret: The webhook signing secret (whsec_...).

        Returns:
            Parsed event dict with keys: id, type, data, created, etc.

        Raises:
            stripe.error.SignatureVerificationError: if signature is invalid.
            ValueError: if payload cannot be parsed.
        """
        import json
        try:
            # Decode bytes to string for signature verification
            payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else payload

            # Verify signature using Stripe's proven method
            stripe.WebhookSignature.verify_header(
                payload_str, sig_header, webhook_secret
            )

            # Parse JSON directly — avoids Event._construct_from issues in v15
            event_data = json.loads(payload_str)

            logger.info(
                "Stripe webhook event verified: type=%s id=%s",
                event_data.get("type"),
                event_data.get("id"),
            )
            return event_data
        except StripeError as exc:
            logger.error("Stripe webhook signature verification failed: %s", exc)
            raise
