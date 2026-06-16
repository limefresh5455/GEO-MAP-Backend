from fastapi import APIRouter
from app.api.v1 import (
    auth,
    discovery,
    knowledge,
    locations,
    place_details,
    place_photos,
    place_qa,
    routes,
)

api_router = APIRouter(prefix="/api/v1")

# Authentication routes
api_router.include_router(auth.router)

# Location management routes
api_router.include_router(locations.router)

# Discovery routes (Phase 1 - Text Search + Nearby + Router)
api_router.include_router(discovery.router)

# Place Details routes (Phase 2)
api_router.include_router(place_details.router)

# Place Photos routes (Phase 6 - Photos Feature)
api_router.include_router(place_photos.router)

# Knowledge Sync routes (Phase 3)
api_router.include_router(knowledge.router)

# Place Q&A routes (Phase 4)
api_router.include_router(place_qa.router)

# Routes API (Phase 5 - Directions + Route Matrix)
api_router.include_router(routes.router)
