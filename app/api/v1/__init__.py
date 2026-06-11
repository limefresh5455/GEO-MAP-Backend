from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.locations import router as location_router
from app.api.v1.places import router as places_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(location_router)
api_router.include_router(places_router)
