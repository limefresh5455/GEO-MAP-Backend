from typing import Optional
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Google Places
    GOOGLE_PLACES_API_KEY: str
    GOOGLE_PLACES_BASE_URL: str = "https://places.googleapis.com/v1"

    # Google Routes API (shares the same API key as Places)
    GOOGLE_ROUTES_BASE_URL: str = "https://routes.googleapis.com/directions/v2"
    # Redis TTL for route cache (shorter than place details — traffic changes frequently)
    REDIS_ROUTES_CACHE_TTL: int = 300          # 5 minutes
    REDIS_ROUTE_MATRIX_CACHE_TTL: int = 120    # 2 minutes (matrix is used for live ETAs)

    # Place Photos — Redis TTL for resolved CDN photo URLs
    # Photo CDN URLs are stable for a few hours; 1 hour is safe.
    REDIS_PHOTOS_CACHE_TTL: int = 3600         # 1 hour

    # Autocomplete (Phase 2) — Redis TTL for autocomplete predictions
    # Autocomplete results change frequently (businesses open/close), so shorter TTL.
    REDIS_AUTOCOMPLETE_CACHE_TTL: int = 300    # 5 minutes

    # Auto Knowledge Sync (Phase 3) — automatically sync place knowledge to Pinecone
    # after fetching place details, eliminating the manual sync step.
    AUTO_SYNC_KNOWLEDGE_ON_DETAILS_FETCH: bool = True  # set to False to disable

    # Redis (B-007 fix: password should be Optional, not empty string)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_CACHE_TTL: int = 3600         # 60 minutes — search results
    REDIS_DETAILS_CACHE_TTL: int = 86400  # 24 hours — place details (rarely change)
    DETAILS_STALE_AFTER_DAYS: int = 7

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"          # used by Place Q&A (Phase 4)
    OPENAI_MAX_CONTEXT_TOKENS: int = 3000            # token budget for RAG context

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "geo-map-places"
    PINECONE_ENVIRONMENT: str = ""      # e.g. "us-east-1-aws" for serverless

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # B-005 FIX: Field validators run before model construction, catching missing values early
    @field_validator("SECRET_KEY", "GOOGLE_PLACES_API_KEY", "OPENAI_API_KEY", "PINECONE_API_KEY")
    @classmethod
    def validate_required_secret(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v

    # B-006 FIX: Validate DATABASE_URL format
    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DATABASE_URL must not be empty")
        if not v.startswith(("postgresql://", "postgresql+psycopg2://")):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL connection string")
        return v


settings = Settings()
