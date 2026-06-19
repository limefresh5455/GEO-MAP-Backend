from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.database.connection import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    MessageResponse,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services.token_blacklist_service import TokenBlacklistService

bearer_scheme = HTTPBearer()

# Initialize limiter for this router
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["Authentication"])

def _user_to_response(user: User) -> UserResponse:

    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        credits=user.credits,
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def signup(request: Request, payload: SignupRequest, db: Session = Depends(get_db)):
    """
    Register new user.
    
    **Request body:**
    ```json
    {
      "full_name": "John Doe",
      "email": "john@example.com",
      "password": "SecurePass@123"
    }
    ```
    """
    # B-021 FIX: Use try-except to catch IntegrityError on race condition
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        # If commit failed due to unique constraint (race condition), return friendly error
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        raise

    return _user_to_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Login and get access token.
    
    **Request body:**
    ```json
    {
      "email": "john@example.com",
      "password": "SecurePass@123"
    }
    ```
    """
    user = db.query(User).filter(User.email == payload.email).first()

    if not user:
        # B06 FIX: Run a dummy bcrypt check to normalise response time.
        # Without this, a missing user returns in <1ms while a wrong password
        # takes ~100ms — measurable difference that reveals user existence.
        verify_password(payload.password, DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
):
    token = credentials.credentials
    
    # Blacklist the token
    success = await TokenBlacklistService.blacklist_token(token)
    
    if not success:
        # Redis unavailable - FAIL the logout to prevent security issue
        # User should not think they've logged out when token is still valid
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Logout service temporarily unavailable. "
            "Token revocation system (Redis) is offline. "
            "Please try again later or contact support if the issue persists."
        )
    
    return MessageResponse(
        message=f"User '{current_user.email}' logged out successfully. "
        "Token has been revoked and is no longer valid."
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return _user_to_response(current_user)
