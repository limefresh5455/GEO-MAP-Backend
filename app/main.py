import logging
import sys
import httpx
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from .api.v1 import api_router
from .core.redis import close_redis, initialise_redis

# Enhanced logging configuration with file handler for crash logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log", mode="a", encoding="utf-8"),
    ]
)

logger = logging.getLogger(__name__)

# Separate logger for crash detection
crash_logger = logging.getLogger("crash_detector")
crash_handler = logging.FileHandler("logs/crashes.log", mode="a", encoding="utf-8")
crash_handler.setLevel(logging.ERROR)
crash_handler.setFormatter(
    logging.Formatter("%(asctime)s | CRASH | %(name)s | %(message)s\n%(exc_info)s\n")
)
crash_logger.addHandler(crash_handler)
crash_logger.setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting geo-map-backend...")

    # B-020 FIX: Initialize rate limiter and attach to app.state
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    logger.info("Rate limiter initialized")
    
    # 1. Redis — B05 FIX: non-fatal startup; degrade gracefully
    await initialise_redis()

    # 2. Pinecone singleton — B04 FIX: index cached once at startup
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

    # 3a. OpenAI singleton — B24 FIX: one AsyncOpenAI connection pool
    openai_client = OpenAIEmbeddingClient()
    app.state.openai_client = openai_client
    logger.info("OpenAI client initialised — model: %s", settings.OPENAI_EMBEDDING_MODEL)

    # 3b. Shared httpx clients — B10 FIX: one connection pool per service
    google_timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    app.state.http_nearby = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    app.state.http_text_search = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    app.state.http_place_details = httpx.AsyncClient(timeout=google_timeout, limits=limits)

    # Autocomplete client (Phase 2) — fast response times expected
    app.state.http_autocomplete = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    logger.info("Autocomplete httpx client initialised.")

    # Place Photos client — follow_redirects is handled inside the client,
    # but we still want a shared connection pool for the CDN hit after redirect.
    app.state.http_photos = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    logger.info("Place Photos httpx client initialised.")

    # Routes API client — uses a slightly longer read timeout because route
    # computation (especially traffic-aware) can take longer than a Places lookup.
    routes_timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    app.state.http_routes = httpx.AsyncClient(timeout=routes_timeout, limits=limits)
    logger.info("Routes API httpx client initialised.")

    app.state.http_open_meteo = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    logger.info("Open-Meteo httpx client initialised.")

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
    await app.state.http_autocomplete.aclose()
    await app.state.http_photos.aclose()
    await app.state.http_routes.aclose()
    await app.state.http_open_meteo.aclose()
    logger.info("httpx clients closed.")

    # B14 FIX: Shut down Pinecone thread pool executor
    from app.integrations.pinecone_client import shutdown_executor
    shutdown_executor()

    # Close Redis
    await close_redis()
    logger.info("geo-map-backend shutdown complete.")


app = FastAPI(
    title="Geo Map Backend",
    version="3.0.0",
    lifespan=lifespan,
)

# ----------------------------------------------------------------
# CORS Middleware — allows frontend to communicate with backend
# ----------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],             
    expose_headers=["*"],             
    max_age=3600,                     
)

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# Global Exception Handlers for Crash Detection
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and log them for crash detection."""
    crash_logger.error(
        f"UNHANDLED EXCEPTION: {type(exc).__name__}\n"
        f"Path: {request.method} {request.url.path}\n"
        f"User-Agent: {request.headers.get('user-agent', 'unknown')}\n"
        f"Error: {str(exc)}\n"
        f"Traceback: {''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}",
        exc_info=True
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "Internal server error occurred. The issue has been logged.",
            "error_type": type(exc).__name__,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "Validation error",
            "errors": exc.errors(),
            "timestamp": datetime.utcnow().isoformat()
        }
    )


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

    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter the JWT token from POST /api/v1/auth/login",
        }
    }

    schema["security"] = [{"BearerAuth": []}]
    for path_data in schema.get("paths", {}).values():
        for operation in path_data.values():
            if isinstance(operation, dict) and "security" in operation:
                operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
