import logging
from typing import List, Optional
from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session
from app.models.ai_chat_message import AIChatMessage
from app.models.ai_chat_session import AIChatSession

logger = logging.getLogger(__name__)


class AIChatRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------
    # Sessions
    # ------------------------------

    def create_session(self, *, user_id: int, title: str = "New Chat") -> AIChatSession:
        session = AIChatSession(user_id=user_id, title=title)
        self.db.add(session)
        self.db.flush()  # so session.id is available immediately
        logger.info("Created AIChatSession id=%r for user_id=%s", session.id, user_id)
        return session

    def get_session(self, *, session_id: str, user_id: int) -> Optional[AIChatSession]:
        return (
            self.db.query(AIChatSession)
            .filter(
                and_(
                    AIChatSession.id == session_id,
                    AIChatSession.user_id == user_id,
                )
            )
            .first()
        )

    def count_user_sessions(self, *, user_id: int) -> int:
        return (
            self.db.query(func.count(AIChatSession.id))
            .filter(
                and_(
                    AIChatSession.user_id == user_id,
                    AIChatSession.is_archived.is_(False),
                )
            )
            .scalar()
            or 0
        )

    def update_session_timestamp(self, *, session: AIChatSession) -> None:
        """Set last_message_at to the timestamp of the most recent message."""
        last_msg = (
            self.db.query(func.max(AIChatMessage.created_at))
            .filter(AIChatMessage.session_id == session.id)
            .scalar()
        )
        session.last_message_at = last_msg
        self.db.flush()

    def archive_session(self, *, session: AIChatSession) -> None:
        session.is_archived = True
        self.db.flush()

    # ------------------------------
    # Messages
    # ------------------------------

    def add_message(
        self,
        *,
        session_id: str,  # UUID string (was int)
        role: str,
        content: str,
        token_count: Optional[int] = None,
        model_used: Optional[str] = None,
    ) -> AIChatMessage:
        """Append a message to a session. Flushed but not committed."""
        msg = AIChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            model_used=model_used,
        )
        self.db.add(msg)
        self.db.flush()
        return msg

    def get_recent_messages(
        self, *, session_id: str, limit: int = 10
    ) -> List[AIChatMessage]:
        """Return the N most recent messages in chronological order."""
        messages = (
            self.db.query(AIChatMessage)
            .filter(AIChatMessage.session_id == session_id)
            .order_by(desc(AIChatMessage.created_at))
            .limit(limit)
            .all()
        )
        return messages[::-1]  # reverse to chronological order

    def count_session_messages(self, *, session_id: str) -> int:
        """Count total messages in a session."""
        return (
            self.db.query(func.count(AIChatMessage.id))
            .filter(AIChatMessage.session_id == session_id)
            .scalar()
            or 0
        )

    def list_messages_paginated(
        self, *, session_id: str, limit: int, offset: int
    ) -> List[AIChatMessage]:
        """Paginated message listing in chronological order."""
        return (
            self.db.query(AIChatMessage)
            .filter(AIChatMessage.session_id == session_id)
            .order_by(AIChatMessage.created_at.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )
