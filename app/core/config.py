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

    # Google Routes API (shares the same API key as Places)
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
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"  # used by Place Q&A (Phase 4)
    OPENAI_MAX_CONTEXT_TOKENS: int = 3000  # token budget for RAG context

    # Place Q&A Session Limits
    MAX_SESSIONS_PER_USER: int = 100  # Maximum active sessions per user
    MAX_SESSION_AGE_DAYS: int = 90  # Auto-archive sessions older than this

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "geo-map-places"
    PINECONE_ENVIRONMENT: str = ""  # e.g. "us-east-1-aws" for serverless

    # ── SMTP (local custom auth — email OTP) ─────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "GeoMap"
    SMTP_FROM_EMAIL: str = ""

    # OTP settings
    OTP_EXPIRE_SECONDS: int = 120  # 2 minutes
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
