import logging
import os
import sys
import httpx
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.rate_limiter import shared_limiter
from app.integrations.pinecone_client import PineconeClient
from app.integrations.openai_client import OpenAIEmbeddingClient
from .api.v1 import api_router
from .core.redis import close_redis, initialise_redis
from UI.main import router as ui_router

# Ensure logs directory exists before FileHandler is created
os.makedirs("logs", exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log", mode="a", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

crash_logger = logging.getLogger("crash_detector")
crash_handler = logging.FileHandler("logs/crashes.log", mode="a", encoding="utf-8")
crash_handler.setLevel(logging.ERROR)
crash_handler.setFormatter(
    logging.Formatter("%(asctime)s | CRASH | %(name)s | %(message)s\n%(exc_info)s\n")
)
crash_logger.addHandler(crash_handler)
crash_logger.setLevel(logging.ERROR)


# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting geo-map-backend...")

    # 1. Rate limiter — single shared instance used across all routers
    app.state.limiter = shared_limiter
    logger.info("Rate limiter initialized (shared instance)")

    # 2. Redis — non-fatal; app degrades gracefully if unavailable
    await initialise_redis()

    # 4. Pinecone singleton — index cached once at startup
    pinecone_client = PineconeClient()
    if settings.PINECONE_API_KEY:
        try:
            await pinecone_client.initialise()
        except Exception as exc:
            logger.warning(
                "Pinecone initialisation failed at startup — "
                "knowledge sync and Q&A will fail until resolved: %s",
                exc,
            )
    else:
        logger.warning(
            "PINECONE_API_KEY not set — Pinecone client inactive. "
            "Knowledge sync and Q&A endpoints will return errors."
        )
    app.state.pinecone_client = pinecone_client

    # 5. OpenAI singleton — one AsyncOpenAI connection pool
    openai_client = OpenAIEmbeddingClient()
    app.state.openai_client = openai_client
    logger.info(
        "OpenAI client initialised — model: %s", settings.OPENAI_EMBEDDING_MODEL
    )

    # 6. Shared httpx clients — one connection pool per external service
    google_timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    app.state.http_nearby = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    app.state.http_text_search = httpx.AsyncClient(
        timeout=google_timeout, limits=limits
    )
    app.state.http_place_details = httpx.AsyncClient(
        timeout=google_timeout, limits=limits
    )

    app.state.http_autocomplete = httpx.AsyncClient(
        timeout=google_timeout, limits=limits
    )
    logger.info("Autocomplete httpx client initialised.")

    routes_timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    app.state.http_routes = httpx.AsyncClient(timeout=routes_timeout, limits=limits)
    logger.info("Routes API httpx client initialised.")

    app.state.http_open_meteo = httpx.AsyncClient(timeout=google_timeout, limits=limits)
    logger.info("Open-Meteo httpx client initialised.")

    logger.info("geo-map-backend ready.")
    yield

    # Shutdown
    logger.info("Shutting down geo-map-backend...")

    # Close httpx connection pools first
    await app.state.http_nearby.aclose()
    await app.state.http_text_search.aclose()
    await app.state.http_place_details.aclose()
    await app.state.http_autocomplete.aclose()
    await app.state.http_routes.aclose()
    await app.state.http_open_meteo.aclose()
    logger.info("httpx clients closed.")

    # Pinecone thread pool executor
    try:
        from app.integrations.pinecone_client import shutdown_executor

        shutdown_executor()
    except Exception as exc:
        logger.warning("Pinecone executor shutdown encountered an issue: %s", exc)

    # Redis last
    await close_redis()
    logger.info("geo-map-backend shutdown complete.")


# App
app = FastAPI(
    title="Geo Map Backend",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS
# CORS — use specific origins in production; wildcard + credentials is invalid per CORS spec
# See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS/Errors/CORSNotSupportingCredentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Changed from True — wildcard origin cannot use credentials
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Authorization", "X-Chat-Session-Id"],
    max_age=3600,
)

# Rate limiting + SlowAPI
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Custom local auth (email + password + OTP) is active


# Global exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    crash_logger.error(
        "UNHANDLED EXCEPTION: %s\nPath: %s %s\nUser-Agent: %s\nError: %s\nTraceback: %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        request.headers.get("user-agent", "unknown"),
        str(exc),
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "Internal server error occurred. The issue has been logged.",
            "error_type": type(exc).__name__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "Validation error",
            "errors": exc.errors(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Routers
app.include_router(api_router)

# UI — API Tester Dashboard
app.include_router(ui_router)
app.mount("/ui/static", StaticFiles(directory="UI/static"), name="ui_static")


@app.get("/", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "service": "geo-map-backend",
        "version": "3.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Custom OpenAPI — single BearerAuth scheme
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
