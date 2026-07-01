"""
tests/test_payment_workflow.py
==============================
Unit tests for the payment workflow covering all five issues fixed:

  Issue 1 — /payments/confirm must reject non-succeeded PaymentIntents
  Issue 2 — resolve_credits() must match on package name AND amount
  Issue 3 — (config gap — verified via .env.example, no runnable test needed)
  Issue 4 — credit_user() must use a row-level lock (get_by_stripe_id_for_update)
  Issue 5 — credit_user() must NOT call db.commit() internally

All external dependencies (Stripe, DB, email) are mocked so these tests run
without any live credentials or database connection.

NOTE on route-handler tests (Issues 1 & 5 webhook):
  The @limiter.limit decorator wraps the route function in a slowapi shim that
  requires a real Starlette Request object.  We bypass it by calling
  func.__wrapped__ (the original coroutine before the decorator was applied).
  _unwrap() walks the full __wrapped__ chain to handle multiple decorators.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_txn(status_value="pending", credits=50, user_id=1, pi_id="pi_test123"):
    """Return a mock PaymentTransaction with controllable attributes."""
    from app.models.payment_transaction import PaymentStatus

    txn = MagicMock()
    txn.id = 42
    txn.user_id = user_id
    txn.credits_purchased = credits
    txn.amount_inr = 150
    txn.stripe_payment_intent_id = pi_id
    txn.status = PaymentStatus(status_value)
    return txn


def _make_user(user_id=1, credits=100):
    """Return a mock User with controllable attributes."""
    user = MagicMock()
    user.id = user_id
    user.credits = credits
    user.email = "test@example.com"
    user.full_name = "Test User"
    return user


def _unwrap(func):
    """
    Walk the __wrapped__ decorator chain to recover the original coroutine.

    slowapi's @limiter.limit uses functools.wraps, so the original function
    is always reachable via __wrapped__.  We keep walking until there are no
    more layers so this works regardless of how many decorators are stacked.
    """
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


# ─────────────────────────────────────────────────────────────────────────────
# Issue 2 — resolve_credits()
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveCredits:
    """Issue 2: package lookup must match on name AND amount."""

    def test_custom_amount_correct(self):
        from app.services.payment_service import resolve_credits

        assert resolve_credits(150, "custom") == 50    # 150 // 3
        assert resolve_credits(300, "custom") == 100   # 300 // 3
        assert resolve_credits(3, "custom") == 1

    def test_named_package_correct_amount(self):
        from app.services.payment_service import resolve_credits

        assert resolve_credits(150, "starter") == 50
        assert resolve_credits(300, "popular") == 110
        assert resolve_credits(500, "pro") == 190
        assert resolve_credits(1000, "ultimate") == 400

    def test_named_package_wrong_amount_raises(self):
        """
        Before the fix this would silently return credits for whichever package
        matched the INR amount, or fall through to custom calculation.
        After the fix it must raise ValueError.
        """
        from app.services.payment_service import resolve_credits

        with pytest.raises(ValueError, match="does not match"):
            resolve_credits(300, "starter")   # starter expects ₹150

        with pytest.raises(ValueError, match="does not match"):
            resolve_credits(150, "popular")   # popular expects ₹300

        with pytest.raises(ValueError, match="does not match"):
            resolve_credits(999, "pro")       # pro expects ₹500

    def test_custom_below_minimum_raises(self):
        from app.services.payment_service import resolve_credits

        with pytest.raises(ValueError, match="Minimum amount"):
            resolve_credits(2, "custom")

    def test_unknown_package_falls_back_to_custom(self):
        """Unknown package names fall back to custom calculation without an error."""
        from app.services.payment_service import resolve_credits

        # 99 // 3 == 33
        result = resolve_credits(99, "nonexistent_package")
        assert result == 33


# ─────────────────────────────────────────────────────────────────────────────
# Issue 4 — credit_user() uses the locked read
# ─────────────────────────────────────────────────────────────────────────────


class TestCreditUserUsesLockedRead:
    """Issue 4: credit_user must call get_by_stripe_id_for_update, not the plain read."""

    def test_uses_for_update_query(self):
        from app.services.payment_service import PaymentService

        db = MagicMock()
        svc = PaymentService(db)

        txn = _make_txn("pending")
        user = _make_user(credits=100)

        svc.payment_repo.get_by_stripe_id_for_update = MagicMock(return_value=txn)
        svc.payment_repo.get_by_stripe_id = MagicMock()  # must NOT be called
        svc.payment_repo.mark_succeeded = MagicMock(return_value=txn)
        svc.user_repo.get_by_id = MagicMock(return_value=user)

        svc.credit_user("pi_test123")

        svc.payment_repo.get_by_stripe_id_for_update.assert_called_once_with("pi_test123")
        svc.payment_repo.get_by_stripe_id.assert_not_called()

    def test_idempotency_already_succeeded(self):
        """
        If the transaction is already SUCCEEDED the second concurrent caller
        must get the user back without crediting again.
        """
        from app.services.payment_service import PaymentService

        db = MagicMock()
        svc = PaymentService(db)

        txn = _make_txn("succeeded", credits=50)
        user = _make_user(credits=150)

        svc.payment_repo.get_by_stripe_id_for_update = MagicMock(return_value=txn)
        svc.payment_repo.mark_succeeded = MagicMock()
        svc.user_repo.get_by_id = MagicMock(return_value=user)

        result = svc.credit_user("pi_test123")

        svc.payment_repo.mark_succeeded.assert_not_called()
        assert result is user
        assert user.credits == 150  # unchanged


# ─────────────────────────────────────────────────────────────────────────────
# Issue 5 — credit_user() does NOT commit internally
# ─────────────────────────────────────────────────────────────────────────────


class TestCreditUserNoInternalCommit:
    """Issue 5: commit ownership belongs to the route handler, not the service."""

    def test_no_commit_called_on_db(self):
        from app.services.payment_service import PaymentService

        db = MagicMock()
        svc = PaymentService(db)
        txn = _make_txn("pending", credits=50)
        user = _make_user(credits=100)

        svc.payment_repo.get_by_stripe_id_for_update = MagicMock(return_value=txn)
        svc.payment_repo.mark_succeeded = MagicMock(return_value=txn)
        svc.user_repo.get_by_id = MagicMock(return_value=user)

        svc.credit_user("pi_test123")

        db.commit.assert_not_called()

    def test_flush_is_called(self):
        """flush() must still be called so the new balance is visible in the transaction."""
        from app.services.payment_service import PaymentService

        db = MagicMock()
        svc = PaymentService(db)
        txn = _make_txn("pending", credits=50)
        user = _make_user(credits=100)

        svc.payment_repo.get_by_stripe_id_for_update = MagicMock(return_value=txn)
        svc.payment_repo.mark_succeeded = MagicMock(return_value=txn)
        svc.user_repo.get_by_id = MagicMock(return_value=user)

        svc.credit_user("pi_test123")

        db.flush.assert_called_once()

    def test_credits_added_correctly(self):
        from app.services.payment_service import PaymentService

        db = MagicMock()
        svc = PaymentService(db)
        txn = _make_txn("pending", credits=50)
        user = _make_user(credits=100)

        svc.payment_repo.get_by_stripe_id_for_update = MagicMock(return_value=txn)
        svc.payment_repo.mark_succeeded = MagicMock(return_value=txn)
        svc.user_repo.get_by_id = MagicMock(return_value=user)

        result = svc.credit_user("pi_test123")

        assert result is user
        assert user.credits == 150  # 100 + 50


# ─────────────────────────────────────────────────────────────────────────────
# Issue 1 — /payments/confirm rejects non-succeeded PaymentIntents
# Uses _unwrap() to bypass the slowapi rate-limiter shim.
# ─────────────────────────────────────────────────────────────────────────────


class TestConfirmPaymentStatusGate:
    """Issue 1: the confirm endpoint must return 402 for non-succeeded PI statuses."""

    @pytest.mark.asyncio
    async def test_rejects_processing_status(self):
        from fastapi import HTTPException
        from app.api.v1.payments import confirm_payment
        from app.schemas.payments import ConfirmPaymentRequest

        handler = _unwrap(confirm_payment)
        payload = ConfirmPaymentRequest(payment_intent_id="pi_test123")

        with patch(
            "app.api.v1.payments.StripeService.retrieve_payment_intent",
            new=AsyncMock(return_value={"id": "pi_test123", "status": "processing"}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await handler(
                    request=MagicMock(),
                    payload=payload,
                    current_user=_make_user(),
                    db=MagicMock(),
                )

        assert exc_info.value.status_code == 402
        assert "processing" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rejects_canceled_status(self):
        from fastapi import HTTPException
        from app.api.v1.payments import confirm_payment
        from app.schemas.payments import ConfirmPaymentRequest

        handler = _unwrap(confirm_payment)
        payload = ConfirmPaymentRequest(payment_intent_id="pi_test123")

        with patch(
            "app.api.v1.payments.StripeService.retrieve_payment_intent",
            new=AsyncMock(return_value={"id": "pi_test123", "status": "canceled"}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await handler(
                    request=MagicMock(),
                    payload=payload,
                    current_user=_make_user(),
                    db=MagicMock(),
                )

        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_rejects_requires_payment_method_status(self):
        from fastapi import HTTPException
        from app.api.v1.payments import confirm_payment
        from app.schemas.payments import ConfirmPaymentRequest

        handler = _unwrap(confirm_payment)
        payload = ConfirmPaymentRequest(payment_intent_id="pi_test123")

        with patch(
            "app.api.v1.payments.StripeService.retrieve_payment_intent",
            new=AsyncMock(
                return_value={"id": "pi_test123", "status": "requires_payment_method"}
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await handler(
                    request=MagicMock(),
                    payload=payload,
                    current_user=_make_user(),
                    db=MagicMock(),
                )

        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_accepts_succeeded_status(self):
        """Happy path: succeeded PI must not raise and the route handler must commit."""
        from app.api.v1.payments import confirm_payment
        from app.schemas.payments import ConfirmPaymentRequest

        handler = _unwrap(confirm_payment)
        payload = ConfirmPaymentRequest(payment_intent_id="pi_test123")
        mock_db = MagicMock()

        txn = _make_txn("pending", credits=50)
        credited_user = _make_user(credits=150)

        with patch(
            "app.api.v1.payments.StripeService.retrieve_payment_intent",
            new=AsyncMock(return_value={"id": "pi_test123", "status": "succeeded"}),
        ), patch("app.api.v1.payments.PaymentService") as MockSvc:
            inst = MockSvc.return_value
            inst.credit_user.return_value = credited_user
            inst.payment_repo.get_by_stripe_id.return_value = txn

            response = await handler(
                request=MagicMock(),
                payload=payload,
                current_user=_make_user(credits=100),
                db=mock_db,
            )

        mock_db.commit.assert_called_once()
        assert response.credits_added == 50
        assert response.new_balance == 150
        assert response.status == "succeeded"

    @pytest.mark.asyncio
    async def test_confirm_returns_404_when_no_transaction(self):
        """credit_user returning None → 404; no commit should happen."""
        from fastapi import HTTPException
        from app.api.v1.payments import confirm_payment
        from app.schemas.payments import ConfirmPaymentRequest

        handler = _unwrap(confirm_payment)
        payload = ConfirmPaymentRequest(payment_intent_id="pi_unknown")
        mock_db = MagicMock()

        with patch(
            "app.api.v1.payments.StripeService.retrieve_payment_intent",
            new=AsyncMock(return_value={"id": "pi_unknown", "status": "succeeded"}),
        ), patch("app.api.v1.payments.PaymentService") as MockSvc:
            inst = MockSvc.return_value
            inst.credit_user.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await handler(
                    request=MagicMock(),
                    payload=payload,
                    current_user=_make_user(),
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404
        mock_db.commit.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Webhook — commit boundary (Issue 5, webhook side)
# Uses _unwrap() for the same reason as the confirm tests.
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookCommitBoundary:
    """The webhook handler must commit after a successful credit_user call."""

    @pytest.mark.asyncio
    async def test_webhook_commits_after_credit(self):
        from app.api.v1.stripe_webhook import stripe_webhook

        handler = _unwrap(stripe_webhook)
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=b'{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_test123"}}}'
        )
        mock_request.headers = {"stripe-signature": "t=1,v1=abc"}

        mock_db = MagicMock()
        user = _make_user(credits=150)
        txn = _make_txn("succeeded", credits=50)

        with patch(
            "app.api.v1.stripe_webhook.StripeService.construct_webhook_event",
            new=AsyncMock(
                return_value={
                    "type": "payment_intent.succeeded",
                    "data": {"object": {"id": "pi_test123"}},
                }
            ),
        ), patch(
            "app.api.v1.stripe_webhook.PaymentService"
        ) as MockSvc, patch(
            "app.api.v1.stripe_webhook.send_payment_confirmation_email"
        ):
            inst = MockSvc.return_value
            inst.credit_user.return_value = user
            inst.payment_repo.get_by_stripe_id.return_value = txn

            await handler(request=mock_request, db=mock_db)

        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_returns_500_when_credit_fails(self):
        """
        If credit_user returns None (orphaned transaction), return 500 so Stripe
        retries the webhook.  Do NOT commit because no changes were made.
        """
        from app.api.v1.stripe_webhook import stripe_webhook

        handler = _unwrap(stripe_webhook)
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=b'{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_orphan"}}}'
        )
        mock_request.headers = {"stripe-signature": "t=1,v1=abc"}

        mock_db = MagicMock()

        with patch(
            "app.api.v1.stripe_webhook.StripeService.construct_webhook_event",
            new=AsyncMock(
                return_value={
                    "type": "payment_intent.succeeded",
                    "data": {"object": {"id": "pi_orphan"}},
                }
            ),
        ), patch("app.api.v1.stripe_webhook.PaymentService") as MockSvc:
            inst = MockSvc.return_value
            inst.credit_user.return_value = None

            response = await handler(request=mock_request, db=mock_db)

        # Must NOT commit — nothing changed
        mock_db.commit.assert_not_called()

        # Must return 500 so Stripe retries the event
        assert response.status_code == 500
        assert "credit allocation did not complete" in response.body.decode()
