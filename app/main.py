import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.v1 import api_router
from app.core.redis import close_redis, initialise_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle.

    Startup order
    -------------
    1. Redis   — non-fatal; app degrades gracefully if unavailable (B05)
    2. Pinecone — singleton client; index handle cached once (B04)
    3. httpx clients — one shared connection pool per Google service (B10)
    4. Pinecone executor — registered for clean shutdown (B14)
    5. Rate limiter — B-020 FIX: initialized and attached to app.state

    Shutdown order (reverse)
    ------------------------
    1. httpx clients closed
    2. Pinecone executor shut down
    3. Redis connection closed
    """
    logger.info("Starting geo-map-backend...")

    # ----------------------------------------------------------------
    # B-020 FIX: Initialize rate limiter and attach to app.state
    # ----------------------------------------------------------------
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    logger.info("Rate limiter initialized")

    # ----------------------------------------------------------------
    # 1. Redis — B05 FIX: non-fatal startup; degrade gracefully
    # ----------------------------------------------------------------
    await initialise_redis()

    # ----------------------------------------------------------------
    # 2. Pinecone singleton — B04 FIX: index cached once at startup
    # ----------------------------------------------------------------
    from app.core.config import settings  # noqa: PLC0415
    from app.integrations.pinecone_client import PineconeClient  # noqa: PLC0415
    from app.integrations.openai_client import OpenAIEmbeddingClient  # noqa: PLC0415

    pinecone_client = PineconeClient()
    if settings.PINECONE_API_KEY:
        try:
            await pinecone_client.initialise()
        except Exception as exc:
            logger.warning(
                "Pinecone initialisation failed at startup — "
                "knowledge sync and Q&A will fail until resolved: %s", exc
            )
    else:
        logger.warning(
            "PINECONE_API_KEY not set — Pinecone client inactive. "
            "Knowledge sync and Q&A endpoints will return errors."
        )
    app.state.pinecone_client = pinecone_client

    # ----------------------------------------------------------------
    # 3a. OpenAI singleton — B24 FIX: one AsyncOpenAI connection pool
    # ----------------------------------------------------------------
    openai_client = OpenAIEmbeddingClient()
    app.state.openai_client = openai_client
    logger.info("OpenAI client initialised — model: %s", settings.OPENAI_EMBEDDING_MODEL)

    # ----------------------------------------------------------------
    # 3b. Shared httpx clients — B10 FIX: one connection pool per service
    # ----------------------------------------------------------------
    google_timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    app.state.http_nearby = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    app.state.http_text_search = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    app.state.http_place_details = httpx.AsyncClient(timeout=google_timeout, limits=limits)

    logger.info("geo-map-backend ready.")
    yield

    # ----------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------
    logger.info("Shutting down geo-map-backend...")

    # Close httpx connection pools
    await app.state.http_nearby.aclose()
    await app.state.http_text_search.aclose()
    await app.state.http_place_details.aclose()
    logger.info("httpx clients closed.")

    # B14 FIX: Shut down Pinecone thread pool executor
    from app.integrations.pinecone_client import shutdown_executor
    shutdown_executor()

    # Close Redis
    await close_redis()
    logger.info("geo-map-backend shutdown complete.")


app = FastAPI(
    title="Geo Map Backend",
    description=(
        "Location-aware backend with Bearer token authentication, "
        "GPS location tracking, and Redis-cached nearby places search.\n\n"
        "**How to authenticate:**\n"
        "1. POST `/api/v1/auth/signup` to register.\n"
        "2. POST `/api/v1/auth/login` with your email + password to get a token.\n"
        "3. Click **Authorize**, paste the token, click Authorize."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

# B-020 FIX: Rate limiter is now initialized in lifespan and attached to app.state
# The middleware will access it from app.state.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(api_router)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "geo-map-backend", "version": "3.0.0"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Replace ALL auto-generated security schemes with a single plain Bearer scheme.
    # This removes the OAuth2PasswordBearer form and shows only one token input field.
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter the JWT token from POST /api/v1/auth/login",
        }
    }

    # Apply globally so every endpoint uses this single scheme
    schema["security"] = [{"BearerAuth": []}]

    # Also fix per-endpoint security references that FastAPI auto-generated
    # from HTTPBearer — replace any "HTTPBearer" refs with "BearerAuth"
    for path_data in schema.get("paths", {}).values():
        for operation in path_data.values():
            if isinstance(operation, dict) and "security" in operation:
                operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema


# Override FastAPI's default openapi() method
app.openapi = custom_openapi
