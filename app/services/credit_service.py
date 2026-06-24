import logging
from sqlalchemy.orm import Session
from app.exceptions.custom_exceptions import InsufficientCreditsError, NotFoundError
from app.models.user import User

logger = logging.getLogger(__name__)


class CreditService:
    """Small service for checking and deducting user credits."""

    @staticmethod
    async def check_balance(db: Session, user_id: int, required: int) -> None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise NotFoundError(f"User {user_id} not found")

        available = user.credits or 0
        if available < required:
            raise InsufficientCreditsError(required=required, available=available)

    @staticmethod
    async def deduct(db: Session, user_id: int, amount: int) -> int:
        user = db.query(User).filter(User.id == user_id).with_for_update().first()
        if user is None:
            raise NotFoundError(f"User {user_id} not found")

        available = user.credits or 0
        if available < amount:
            raise InsufficientCreditsError(required=amount, available=available)

        user.credits = available - amount
        db.flush()

        logger.info(
            "Deducted %s credits from user %s; remaining=%s",
            amount,
            user_id,
            user.credits,
        )
        return user.credits
