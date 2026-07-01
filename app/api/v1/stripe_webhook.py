# app/api/v1/stripe_webhook.py
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiter import shared_limiter as limiter
from app.database.connection import get_db
from app.models.payment_transaction import PaymentStatus
from app.services.payment_service import PaymentService
from app.services.stripe_service import StripeService

# Email
from app.services.email_service import send_payment_confirmation_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe Webhook"])


@router.post(
    "/webhook",
    summary="Stripe webhook endpoint",
    description=(
        "Receives Stripe webhook events.\n\n"
        "**payment_intent.succeeded** — marks the transaction as succeeded, "
        "credits the user's account, and sends a confirmation email.\n\n"
        "**payment_intent.payment_failed** — marks the transaction as failed.\n\n"
        "This endpoint is **not** authenticated via Bearer token. Instead, it "
        "relies on Stripe's webhook signature verification."
    ),
)
@limiter.limit("60/minute")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    # Verify webhook signature
    try:
        event = await StripeService.construct_webhook_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        logger.warning(
            "Stripe webhook verification failed: %s %s",
            type(exc).__name__,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"Invalid signature: {type(exc).__name__}"},
        )

    event_type = event.get("type")
    event_data = event.get("data")
    data_object = event_data.get("object") if event_data else None
    payment_intent_id = data_object.get("id") if data_object else None

    logger.info(
        "Stripe webhook received: type=%s PI=%s", event_type, payment_intent_id
    )

    # Guard: malformed event with no PaymentIntent ID — ack Stripe but skip processing
    if not payment_intent_id:
        logger.warning(
            "Stripe webhook event type=%s has no PaymentIntent ID — skipping",
            event_type,
        )
        return {"received": True}

    if event_type == "payment_intent.succeeded":
        svc = PaymentService(db)
        user = svc.credit_user(payment_intent_id)

        if user:
            # Commit credit allocation — credit_user() only flushes, the
            # route handler (here) owns the commit boundary.
            db.commit()

            # Send confirmation email (run_in_executor to avoid blocking event loop)
            # Re-fetch txn after commit so we read the final committed state.
            txn = svc.payment_repo.get_by_stripe_id(payment_intent_id)
            if txn:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        send_payment_confirmation_email,
                        user.email,
                        user.full_name,
                        txn.credits_purchased,
                        user.credits,
                        txn.amount_inr,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to send payment confirmation email to %s: %s",
                        user.email,
                        exc,
                    )
        else:
            logger.error(
                "credit_user() returned None for PI=%s on payment_intent.succeeded — "
                "transaction may be missing or user deleted — returning 500 for retry",
                payment_intent_id,
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": (
                        "Failed to process payment — credit allocation did not "
                        "complete. Stripe will retry this webhook."
                    )
                },
            )

        logger.info(
            "Payment succeeded — PI=%s user_id=%s credits=%s balance=%s",
            payment_intent_id,
            user.id,
            txn.credits_purchased if txn else 0,
            user.credits,
        )

    elif event_type == "payment_intent.payment_failed":
        svc = PaymentService(db)
        txn = svc.payment_repo.get_by_stripe_id(payment_intent_id)
        if txn:
            # Never overwrite a SUCCEEDED transaction with FAILED.
            # This guards against rare out-of-order webhook delivery from Stripe.
            if txn.status == PaymentStatus.SUCCEEDED:
                logger.warning(
                    "Ignoring payment_failed event for PI=%s — transaction already SUCCEEDED",
                    payment_intent_id,
                )
            else:
                svc.payment_repo.mark_failed(txn)
                db.commit()
                logger.info(
                    "Payment failed — PI=%s user_id=%s",
                    payment_intent_id,
                    txn.user_id,
                )
        else:
            logger.warning(
                "payment_intent.payment_failed received for unknown PI=%s — no DB record found",
                payment_intent_id,
            )

    return {"received": True}
