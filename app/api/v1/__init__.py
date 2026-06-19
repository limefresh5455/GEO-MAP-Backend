from fastapi import APIRouter
from app.api.v1 import (auth, discovery, knowledge, locations, place_details, place_photos, place_qa, routes, weather, ai_chat,)
api_router = APIRouter(prefix="/api/v1")

# routes
api_router.include_router(auth.router)
api_router.include_router(locations.router)
api_router.include_router(discovery.router)
api_router.include_router(place_details.router)
api_router.include_router(place_photos.router)
api_router.include_router(knowledge.router)
api_router.include_router(place_qa.router)
api_router.include_router(ai_chat.router)
api_router.include_router(routes.router)
api_router.include_router(weather.router)


