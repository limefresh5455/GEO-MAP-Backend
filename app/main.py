import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from app.api.v1 import api_router
from app.core.redis import close_redis, initialise_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle events."""
    logger.info("Starting geo-map-backend...")
    await initialise_redis()
    logger.info("geo-map-backend ready.")
    yield
    logger.info("Shutting down geo-map-backend...")
    await close_redis()


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

    # Replace ALL auto-generated security schemes with a single plain Bearer scheme hello.
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
