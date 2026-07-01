from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 7 days

    # Google Places
    GOOGLE_PLACES_API_KEY: str
    GOOGLE_PLACES_BASE_URL: str = "https://places.googleapis.com/v1"

    # Google Routes API
    GOOGLE_ROUTES_BASE_URL: str = "https://routes.googleapis.com/directions/v2"
    REDIS_ROUTES_CACHE_TTL: int = 300
    REDIS_ROUTE_MATRIX_CACHE_TTL: int = 120
    REDIS_PHOTOS_CACHE_TTL: int = 3600
    REDIS_AUTOCOMPLETE_CACHE_TTL: int = 300
    AUTO_SYNC_KNOWLEDGE_ON_DETAILS_FETCH: bool = True
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_CACHE_TTL: int = 3600
    REDIS_DETAILS_CACHE_TTL: int = 86400
    DETAILS_STALE_AFTER_DAYS: int = 7
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_CONTEXT_TOKENS: int = 3000

    # Place Q&A Session Limits
    MAX_SESSIONS_PER_USER: int = 100
    MAX_SESSION_AGE_DAYS: int = 90

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "geo-map-places"
    PINECONE_ENVIRONMENT: str = ""

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "GeoMap"
    SMTP_FROM_EMAIL: str = ""

    # SMTP settings: TLS toggle
    SMTP_USE_TLS: bool = True

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Exchange Rate (INR → USD conversion for Stripe)
    EXCHANGE_RATE_CACHE_TTL: int = 600  # seconds — how long to cache the live rate (10 min)

    # OTP settings
    OTP_EXPIRE_SECONDS: int = 300  # 5 minutes
    OTP_MAX_ATTEMPTS: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Keep existing validators unchanged
    @field_validator(
        "SECRET_KEY", "GOOGLE_PLACES_API_KEY", "OPENAI_API_KEY", "PINECONE_API_KEY"
    )
    @classmethod
    def validate_required_secret(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        if info.field_name == "SECRET_KEY" and len(v.strip()) < 32:
            raise ValueError(
                f"SECRET_KEY must be at least 32 characters long (got {len(v.strip())})"
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DATABASE_URL must not be empty")
        if not v.startswith(("postgresql://", "postgresql+psycopg2://")):
            raise ValueError(
                "DATABASE_URL must be a valid PostgreSQL connection string"
            )
        return v


settings = Settings()
