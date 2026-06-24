# app/schemas/auth.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

# ── Signup ────────────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100, examples=["Jane Doe"])
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return v.strip()


class SignupResponse(BaseModel):
    message: str
    email: str
    otp_expires_in_seconds: int


# ── Verify OTP ────────────────────────────────────────────────────────────────


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["482910"]
    )


# ── Login ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ── Refresh ───────────────────────────────────────────────────────────────────


class RefreshRequest(BaseModel):
    """POST /auth/refresh — send the refresh_token to get a new token pair."""

    refresh_token: str = Field(
        ..., min_length=1, description="The refresh token issued at login"
    )


# ── Logout ────────────────────────────────────────────────────────────────────


class LogoutRequest(BaseModel):
    """
    POST /auth/logout
    Send the refresh_token in the body alongside the Bearer access token
    so both are blacklisted at once.
    refresh_token is optional — if omitted only the access token is revoked.
    """

    refresh_token: Optional[str] = None


# ── Shared responses ──────────────────────────────────────────────────────────


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    is_active: bool
    email_verified: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
    credits: int

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """
    Returned after login, verify-otp, and refresh.

    access_token   — send on every API request (1 hour)
    refresh_token  — store safely, use only on POST /auth/refresh (7 days)
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds (3600).")
    refresh_expires_in: int = Field(
        description="Refresh token lifetime in seconds (604800)."
    )
    user: UserResponse


class MessageResponse(BaseModel):
    message: str
