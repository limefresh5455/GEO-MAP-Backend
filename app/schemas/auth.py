# app/schemas/auth.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, ValidationInfo

# Common weak passwords that should be rejected
_WEAK_PASSWORDS = {
    "password",
    "password123",
    "12345678",
    "123456789",
    "qwerty123",
    "qwerty1",
    "letmein",
    "welcome",
    "admin123",
    "passw0rd",
    "abc123",
    "monkey",
    "dragon",
    "master",
    "hunter",
    "default",
    "changeme",
    "secret",
    "trustno1",
    "iloveyou",
    "football",
    "baseball",
    "sunshine",
    "princess",
    "1234567890",
}


# ── Reusable password strength validator ──────────────────────────────────────


def validate_password_strength(v: str) -> str:
    """Validate password strength rules. Shared by signup, reset, and change-password."""
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit.")
    if v.isalnum():
        raise ValueError(
            "Password must contain at least one special character (e.g., !@#$%^&*)."
        )
    if v.lower() in _WEAK_PASSWORDS:
        raise ValueError(
            "This password is too common and easy to guess. Please choose a stronger password."
        )
    return v


# ── Email normalisation helper ──────────────────────────────────────────────


def normalize_email(v: str) -> str:
    """Strip whitespace and lowercase the email."""
    return v.strip().lower()


# Signup
class SignupRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100, examples=["Jane Doe"])
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class SignupResponse(BaseModel):
    message: str
    email: str
    otp_expires_in_seconds: int
    otp_sent: bool = Field(
        default=True,
        description=(
            "True when a verification OTP was actually dispatched to the email. "
            "False when the email is already registered and verified — no OTP was sent. "
            "Clients should redirect to login when this is False."
        ),
    )


# ── Verify OTP ────────────────────────────────────────────────────────────────


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["482910"]
    )

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)


# ── Login ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password cannot be empty.")
        return v


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


# ── Resend OTP ────────────────────────────────────────────────────────────────


class ResendOTPRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)


class ResendOTPResponse(BaseModel):
    message: str
    email: str
    otp_expires_in_seconds: int


# ── Verification Status ───────────────────────────────────────────────────────


class VerificationStatusResponse(BaseModel):
    registered: bool = Field(
        ..., description="Whether an account with this email exists in the system."
    )
    email_verified: bool = Field(
        ...,
        description="True if the user has completed OTP verification and can log in.",
    )
    is_pending: bool = Field(
        ...,
        description="True if user registered but hasn't verified OTP yet.",
    )
    message: str = Field(..., description="Human-readable status description.")


# ── Forgot Password ───────────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)


class ForgotPasswordResponse(BaseModel):
    message: str
    email: str
    otp_expires_in_seconds: int


# ── Verify Reset OTP ─────────────────────────────────────────────────────────


class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["482910"]
    )

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)


class VerifyResetOTPResponse(BaseModel):
    message: str
    reset_token: str
    expires_in: int = Field(description="Reset token lifetime in seconds (300).")


# ── Reset Password ────────────────────────────────────────────────────────────


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)
    reset_token: Optional[str] = Field(
        default=None,
        description="Reset token (alternative to X-Reset-Token header).",
    )

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: ValidationInfo) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match.")
        return v

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class ResetPasswordResponse(BaseModel):
    message: str


# ── Change Password (authenticated) ───────────────────────────────────────────


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)
    refresh_token: Optional[str] = Field(
        default=None,
        description="Current refresh_token to blacklist along with access token. Optional but recommended for full session logout.",
    )

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: ValidationInfo) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match.")
        return v

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("new_password")
    @classmethod
    def not_same_as_old(cls, v: str, info: ValidationInfo) -> str:
        if "old_password" in info.data and v == info.data["old_password"]:
            raise ValueError("New password must be different from current password.")
        return v


class ChangePasswordResponse(BaseModel):
    message: str
