# 📝 Change Log

## GeoMap — Location-Based Discovery Platform

---

## v3.0.0 — June 22, 2026

### Bug Fixes — Round 3 (Cosmetic)
- **has_valid_destination()** — Method now also returns `True` when `place_id` is set, not just when lat/lon coordinates are provided (`app/schemas/routes.py`)
- **is_duplicate polarity** — Renamed `is_duplicate` to `is_new` and flipped boolean semantics: `True` now means "new location saved" instead of "unchanged duplicate" (`app/services/location_service.py`, `app/api/v1/locations.py`)

### Bug Fixes — Round 2
- **Refresh token rotation (SAFE ORDER)** — Changed refresh endpoint to issue new tokens FIRST, then blacklist the old token. Previously the old token was blacklisted first — if the server crashed between steps, the user lost access permanently (`app/api/v1/auth.py`)
- **Weather service error consistency** — Changed `WeatherService` to raise `UserLocationNotFoundError` instead of `LocationNotFoundError`, matching `RoutesService` (`app/services/weather_service.py`)
- **Weather API catch block** — Updated `weather.py` to catch the correct error type after the service change (`app/api/v1/weather.py`)
- **Pinecone async fallback** — Made `_get_index()` async and runs fallback init in the thread pool executor to avoid blocking the event loop (`app/integrations/pinecone_client.py`)
- **Location stale objects** — Changed `synchronize_session` from `False` to `'evaluate'` in bulk update methods so the SQLAlchemy session cache stays in sync with the database (`app/repositories/location_repository.py`)

### Bug Fixes — Round 1
- **Double websocket.accept()** — Removed `await websocket.accept()` from `ConnectionManager.connect()` since the caller already calls it. This was causing a `RuntimeError` on every WebSocket connection (`app/core/websocket_manager.py`)
- **ConnectionManager thread safety** — Added `asyncio.Lock` to protect all dict operations against concurrent access. Made `disconnect()` and `is_connected()` async (`app/core/websocket_manager.py`)
- **OTP race condition** — Replaced non-atomic read-modify-write with an atomic Redis Lua script that verifies OTP and increments attempts in one operation (`app/services/otp_service.py`)
- **Routes API bare except** — Removed `except Exception` that was catching system-level exceptions like `SystemExit` (`app/api/v1/routes.py`)
- **WebSocket disconnect awaited** — Updated `ws.py` to `await manager.disconnect()` since it's now async (`app/api/v1/ws.py`)
- **Unused imports removed** — Removed `json` import from `websocket_manager.py`, removed unused `Limiter` from `routes.py`

### Features
- **Full documentation** — Created `docs/` folder with 9 comprehensive documentation files: PRD, TRD, Architecture, Workflow, Decisions, Tasks, Change Log, API Reference, Database Schema

---

## v2.0.0 — Previous Release

### Architecture Changes
- Switched from Clerk authentication to custom JWT auth system
- Removed Clerk middleware and dependencies
- Migrated from old Places API structure to Google Places API (New)
- Removed deprecated `places.py`, `place_photos.py` modules

### New Features
- WebSocket streaming for AI chat and place Q&A
- RAG pipeline with Pinecone vector database
- Refresh token rotation with Redis blacklist
- OTP email verification system
- Rate limiting with SlowAPI

### Database
- Added UUID v4 string PKs for session tables
- Added `place_qa_sessions` and `place_qa_messages` tables
- Added `ai_chat_sessions` and `ai_chat_messages` tables
- 22 total migration files covering all schema changes

---

## v1.0.0 — Initial Release

- Basic FastAPI application setup
- User authentication with Clerk
- Location tracking endpoints
- Google Places text and nearby search
- Place details with caching
- Route computation with Google Routes API
- Weather forecast with Open-Meteo
- Chat conversation system
- Place Q&A with basic RAG
- Redis caching layer
- Docker setup with PostgreSQL and Redis
