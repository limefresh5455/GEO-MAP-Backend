from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.locations import router as location_router
from app.api.v1.places import router as places_router
from app.api.v1.discovery import router as discovery_router
from app.api.v1.place_details import router as place_details_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.place_qa import router as place_qa_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(location_router)
api_router.include_router(places_router)
api_router.include_router(discovery_router)
api_router.include_router(place_details_router)
api_router.include_router(knowledge_router)
api_router.include_router(place_qa_router)
