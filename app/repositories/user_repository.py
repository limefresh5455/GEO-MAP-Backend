# app/repositories/user_repository.py
import logging
from typing import Optional
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app.models.user import User

logger = logging.getLogger(__name__)

# bcrypt context — used for hashing and verifying passwords
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the bcrypt hash."""
    return _pwd_context.verify(plain, hashed)


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def get_active_by_id(self, user_id: int) -> Optional[User]:
        return (
            self.db.query(User)
            .filter(User.id == user_id, User.is_active == True)
            .first()
        )

    def create_pending_user(
        self,
        *,
        full_name: str,
        email: str,
        hashed_password: str,
    ) -> User:
        """
        Create a user in 'pending' state (not yet active, not verified).
        The user will be activated after OTP verification.
        This avoids storing the hashed password in Redis.
        """
        user = User(
            full_name=full_name,
            email=email,
            hashed_password=hashed_password,
            auth_provider="local",
            email_verified=False,
            is_active=False,
            credits=0,
        )
        self.db.add(user)
        self.db.flush()
        logger.info("Created pending user for OTP flow: email=%s id=%s", email, user.id)
        return user

    def activate_pending_user(self, user: User) -> User:
        """
        Activate a user after successful OTP verification.
        """
        user.email_verified = True
        user.is_active = True
        user.credits = 50
        self.db.flush()
        logger.info("Activated user after OTP: id=%s email=%s", user.id, user.email)
        return user

    def delete_pending_user(self, user: User) -> None:
        """Delete a pending user (e.g., on OTP expiry or cleanup)."""
        self.db.delete(user)
        self.db.flush()
        logger.info("Deleted pending user: id=%s email=%s", user.id, user.email)

    def deactivate(self, user: User) -> User:
        user.is_active = False
        self.db.flush()
        logger.info("Deactivated user id=%s", user.id)
        return user
