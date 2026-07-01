# app/api/v1/payments.py
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from stripe import StripeError

from app.core.rate_limiter import shared_limiter as limiter
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.core.config import settings
from app.schemas.payments import (
    ConfirmPaymentRequest,
    ConfirmPaymentResponse,
    CreatePaymentIntentRequest,
    CreatePaymentIntentResponse,
    PackagesResponse,
    PaymentHistoryItem,
    PaymentHistoryResponse,
    PaymentPackage,
    StripeConfigResponse,
)
from app.services.payment_service import (
    CREDIT_PACKAGES,
    PaymentService,
    resolve_credits,
)
from app.services.stripe_service import StripeService
from app.services.exchange_rate_service import get_inr_to_usd_rate, inr_to_usd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])

# ── STEP 1 ── GET /api/v1/payments/config ────────────────────────────────────


@router.get(
    "/config",
    response_model=StripeConfigResponse,
    summary="[Step 1] Get Stripe publishable key",
    description=(
        "Returns the Stripe publishable key needed by the frontend to initialise "
        "Stripe.js and Stripe Elements.\n\n"
        "**Why you need this:** The publishable key (`pk_test_...`) is used by "
        "Stripe.js on the frontend to securely collect card details and create "
        "a payment method. It is safe to expose to the browser — it cannot be "
        "used to make charges.\n\n"
        "No authentication required. Call this once on page load."
    ),
)
@limiter.limit("30/minute")
async def get_stripe_config(
    request: Request,
):
    return StripeConfigResponse(
        publishable_key=settings.STRIPE_PUBLISHABLE_KEY,
    )


# ── STEP 2 ── GET /api/v1/payments/packages ──────────────────────────────────


@router.get(
    "/packages",
    response_model=PackagesResponse,
    summary="[Step 2] Get available credit packages",
    description=(
        "Returns all fixed-price credit packages and custom pricing info.\n\n"
        "**Packages:**\n"
        "- Starter  → ₹150  / 50 credits\n"
        "- Popular  → ₹300  / 110 credits\n"
        "- Pro      → ₹500  / 190 credits\n"
        "- Ultimate → ₹1000 / 400 credits\n\n"
        "**Custom pricing:** 1 credit per ₹3 (floored), minimum ₹3.\n\n"
        "No authentication required."
    ),
)
@limiter.limit("30/minute")
async def get_packages(
    request: Request,
):
    return PackagesResponse(
        packages=[PaymentPackage(**pkg) for pkg in CREDIT_PACKAGES],
        custom_pricing={
            "min_amount_inr": 3,
            "credits_per_inr": "1 credit per ₹3 (floored)",
        },
    )


# ── STEP 3 ── POST /api/v1/payments/create-intent ────────────────────────────


@router.post(
    "/create-intent",
    response_model=CreatePaymentIntentResponse,
    summary="[Step 3] Create a Stripe PaymentIntent",
    description=(
        "Creates a Stripe PaymentIntent and returns the `client_secret` needed "
        "to complete the payment.\n\n"
        "**What happens inside:**\n"
        "1. Credits are calculated for the chosen package.\n"
        "2. Live INR→USD exchange rate is fetched (cached 10 min in Redis).\n"
        "3. Amount is converted to USD cents and sent to Stripe.\n"
        "4. A pending transaction is saved in the database.\n\n"
        "**After this call:**\n"
        "- Frontend: pass `client_secret` to `stripe.confirmCardPayment()`.\n"
        "- Testing (CLI): run `stripe payment_intents confirm <payment_intent_id> "
        "--payment-method pm_card_visa`\n\n"
        "Requires authentication."
    ),
)
@limiter.limit("10/minute")
async def create_payment_intent(
    request: Request,
    payload: CreatePaymentIntentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 1. Calculate credits — raises ValueError if a named package amount mismatches
    try:
        credits = resolve_credits(payload.amount_inr, payload.package)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # 2. Fetch live exchange rate and convert INR → USD
    try:
        rate = await get_inr_to_usd_rate()
    except RuntimeError as exc:
        logger.error("Exchange rate fetch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to fetch the current INR/USD exchange rate. "
                "Please try again in a moment."
            ),
        ) from exc

    amount_usd = inr_to_usd(payload.amount_inr, rate)
    amount_cents = int(round(amount_usd * 100))

    # Guard: Stripe requires at least $0.50 USD
    if amount_cents < 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The converted amount (${amount_usd:.2f} USD) is below Stripe's "
                "minimum charge of $0.50. Please increase the INR amount."
            ),
        )

    # 3. Create Stripe PaymentIntent in USD
    stripe_result = await StripeService.create_payment_intent(
        amount_paise=amount_cents,
        currency="usd",
        metadata={
            "user_id": str(current_user.id),
            "credits": str(credits),
            "amount_inr": str(payload.amount_inr),
            "exchange_rate": str(rate),
        },
    )

    # 4. Save pending transaction in DB (currency is always USD)
    svc = PaymentService(db)
    svc.create_pending_transaction(
        user_id=current_user.id,
        amount_inr=payload.amount_inr,
        credits=credits,
        payment_intent_id=stripe_result["id"],
        client_secret=stripe_result["client_secret"],
        amount_usd=amount_usd,
        exchange_rate=rate,
        currency="USD",
    )
    db.commit()

    logger.info(
        "PaymentIntent created for user %s: PI=%s amount=₹%s → $%s USD (rate=%s) credits=%s",
        current_user.id,
        stripe_result["id"],
        payload.amount_inr,
        amount_usd,
        rate,
        credits,
    )

    return CreatePaymentIntentResponse(
        client_secret=stripe_result["client_secret"],
        payment_intent_id=stripe_result["id"],
        credits_to_receive=credits,
        amount_inr=payload.amount_inr,
        amount_usd=amount_usd,
        exchange_rate=rate,
        currency="USD",
        plan_currency="INR",
    )


# ── STEP 4 ── POST /api/v1/payments/confirm ──────────────────────────────────


@router.post(
    "/confirm",
    response_model=ConfirmPaymentResponse,
    summary="[Step 4] Confirm payment and allocate credits",
    description=(
        "Call this AFTER the card has been successfully charged by Stripe.\n\n"
        "**Frontend flow:** call this after `stripe.confirmCardPayment()` resolves "
        "with `paymentIntent.status === 'succeeded'`.\n\n"
        "**CLI testing flow:** call this after running:\n"
        "`stripe payment_intents confirm <pi_id> --payment-method pm_card_visa`\n"
        "AND after Terminal 2 (`stripe listen`) shows `[200]` for the webhook.\n\n"
        "**What this does:**\n"
        "1. Re-fetches the PaymentIntent from Stripe to verify status is `succeeded`.\n"
        "2. Marks the transaction as succeeded in the database.\n"
        "3. Adds credits to the user's balance.\n\n"
        "**⚠️ Common mistake:** Do NOT call this immediately after `/create-intent`. "
        "The card must be charged first. If you call this too early you will get: "
        "`Payment is not yet complete. Current Stripe status: requires_payment_method`\n\n"
        "Requires authentication."
    ),
)
@limiter.limit("10/minute")
async def confirm_payment(
    request: Request,
    payload: ConfirmPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 1. Re-verify with Stripe that payment actually succeeded.
    #    Prevents free-credit exploits from calling /confirm on an uncharged PI.
    try:
        pi_data = await StripeService.retrieve_payment_intent(
            payload.payment_intent_id
        )
    except StripeError as exc:
        logger.error(
            "Stripe API error retrieving PI=%s for user=%s: %s",
            payload.payment_intent_id,
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Unable to verify payment status with Stripe. "
                "Please try again in a moment."
            ),
        ) from exc

    logger.info(
        "Confirm request for PI=%s user=%s (stripe_status=%s)",
        payload.payment_intent_id,
        current_user.id,
        pi_data["status"],
    )

    if pi_data["status"] != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Payment is not yet complete. "
                f"Current Stripe status: '{pi_data['status']}'. "
                "Call this endpoint only after Stripe.js reports a successful payment."
            ),
        )

    # 2. Ownership check — verify this PaymentIntent belongs to the requesting user.
    #    Without this, any authenticated user could call /confirm with someone
    #    else's payment_intent_id and claim their credits.
    svc = PaymentService(db)
    txn_check = svc.payment_repo.get_by_stripe_id(payload.payment_intent_id)
    if txn_check is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Transaction not found for this PaymentIntent. "
                "Please create a payment intent first via /payments/create-intent."
            ),
        )
    if txn_check.user_id != current_user.id:
        # Log with full details for security audit; return generic 404 to caller
        # so the existence of the transaction is not revealed.
        logger.warning(
            "Ownership violation: user=%s attempted to confirm PI=%s owned by user=%s",
            current_user.id,
            payload.payment_intent_id,
            txn_check.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Transaction not found for this PaymentIntent. "
                "Please create a payment intent first via /payments/create-intent."
            ),
        )

    # 3. Allocate credits (idempotent — row-locked to prevent race with webhook)
    user = svc.credit_user(payload.payment_intent_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Transaction not found for this PaymentIntent. "
                "Please create a payment intent first via /payments/create-intent."
            ),
        )

    # 4. Commit
    db.commit()

    # 5. Re-fetch transaction for the response (after commit so data is fresh)
    txn = svc.payment_repo.get_by_stripe_id(payload.payment_intent_id)

    logger.info(
        "Payment confirmed via API: PI=%s user=%s credits=%s balance=%s",
        payload.payment_intent_id,
        current_user.id,
        txn.credits_purchased if txn else 0,
        user.credits,
    )

    return ConfirmPaymentResponse(
        credits_added=txn.credits_purchased if txn else 0,
        new_balance=user.credits,
        status=pi_data["status"],
    )


# ── STEP 5 ── GET /api/v1/payments/history ───────────────────────────────────


@router.get(
    "/history",
    response_model=PaymentHistoryResponse,
    summary="[Step 5] Get payment history",
    description=(
        "Returns the 20 most recent payment transactions for the authenticated user.\n\n"
        "Use this after `/confirm` to verify the transaction was recorded with "
        "`status: succeeded` and the correct `credits_purchased`.\n\n"
        "Requires authentication."
    ),
)
@limiter.limit("20/minute")
async def payment_history(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = PaymentService(db)
    transactions = svc.payment_repo.get_user_history(current_user.id)
    return PaymentHistoryResponse(
        transactions=[
            PaymentHistoryItem(
                id=t.id,
                amount_inr=t.amount_inr,
                amount_usd=t.amount_usd,
                exchange_rate=t.exchange_rate,
                credits_purchased=t.credits_purchased,
                status=t.status.value,
                currency=t.currency,
                created_at=t.created_at.replace(tzinfo=timezone.utc)
                if t.created_at and t.created_at.tzinfo is None
                else t.created_at,
                completed_at=t.completed_at.replace(tzinfo=timezone.utc)
                if t.completed_at and t.completed_at.tzinfo is None
                else t.completed_at,
            )
            for t in transactions
        ]
    )
