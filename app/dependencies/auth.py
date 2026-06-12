from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.security import decode_access_token
from app.database.connection import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials  # raw JWT string (without "Bearer " prefix)

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        raise credentials_exception

    # B-016 FIX: Query with is_active check in same statement (atomic)
    # This ensures we always get the current state from DB, not cached JWT data
    user = db.query(User).filter(
        User.id == user_id_int,
        User.is_active == True  # noqa: E712 - SQLAlchemy requires == for bool
    ).first()
    
    if user is None:
        # User either doesn't exist or is_active=False
        raise credentials_exception

    return user
