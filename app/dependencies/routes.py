"""
Dependency providers for the Routes API layer.

Follows the same injection pattern as app/dependencies/discovery.py:
  - Reads the shared httpx.AsyncClient from app.state (B10 pattern)
  - Falls back gracefully to None (per-call client in tests)
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.connection import get_db
from app.integrations.google_routes import GoogleRoutesClient
from app.repositories.redis_repository import RedisRepository
from app.services.routes_service import RoutesService


def get_redis_repo() -> RedisRepository:
    return RedisRepository(get_redis_client())


def get_routes_service(
    request: Request,
    db: Session = Depends(get_db),
    redis_repo: RedisRepository = Depends(get_redis_repo),
) -> RoutesService:
    """
    Construct a RoutesService with a shared httpx client from app.state.

    The http_routes client is registered on app.state during startup in
    app/main.py (see Phase 6 — startup registration).  The getattr fallback
    ensures the app doesn't crash if the key hasn't been set yet (e.g. during
    testing without a full lifespan context).
    """
    http_routes = getattr(request.app.state, "http_routes", None)
    routes_client = GoogleRoutesClient(http_client=http_routes)

    return RoutesService(
        db=db,
        redis_repo=redis_repo,
        routes_client=routes_client,
    )
