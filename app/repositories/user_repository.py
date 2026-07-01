# app/repositories/user_repository.py
import logging
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app.models.user import User

logger = logging.getLogger(__name__)

# bcrypt context — used for hashing and verifying passwords
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email.strip().lower()).first()

    def get_by_email_for_update(self, email: str) -> Optional[User]:
        """
        Same as get_by_email but acquires a row-level lock (SELECT … FOR UPDATE).
        Use this inside the signup transaction to prevent a race condition where
        two concurrent requests both pass the existence check for the same email.
        The first caller locks the row; the second blocks until the first commits.
        """
        return (
            self.db.query(User)
            .filter(User.email == email.strip().lower())
            .with_for_update()
            .first()
        )

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
        user.email_verified = True
        user.is_active = True
        user.credits = 50
        user.password_changed_at = func.now()
        self.db.flush()
        logger.info("Activated user after OTP: id=%s email=%s", user.id, user.email)
        return user

    def delete_pending_user(self, user: User) -> None:
        self.db.delete(user)
        self.db.flush()
        logger.info(f"Deleted pending user: {user.id}, {user.email}")

    def deactivate(self, user: User) -> User:
        user.is_active = False
        self.db.flush()
        logger.info("Deactivated user id=%s", user.id)
        return user

    def update_password(self, user: User, new_hashed_password: str) -> User:
        """Update the user's hashed password, bump timestamps, and record when the password changed."""
        user.hashed_password = new_hashed_password
        user.password_changed_at = func.now()
        self.db.flush()
        logger.info("Password updated for user id=%s", user.id)
        return user
