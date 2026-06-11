# geo-map-backend

A production-style FastAPI backend with JWT authentication, GPS location tracking, and Redis-cached nearby places search using Google Places API (New).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy 2.x |
| Migrations | Alembic |
| Auth | JWT / OAuth2 Bearer |
| Cache | Redis 7 (Docker) |
| Cache Inspector | Redis Insight (Docker) |
| Google API | Google Places API (New) |
| HTTP Client | httpx (async) |
| Password Hash | bcrypt via passlib |
| Settings | pydantic-settings |

---

## Project Structure

```
geo-map-backend/
├── alembic/
│   ├── versions/          ← generated migration files
│   ├── env.py
│   └── script.py.mako
├── app/
│   ├── api/v1/
│   │   ├── auth.py        ← signup, login, logout, /me
│   │   ├── locations.py   ← GPS update, manual update, history
│   │   └── places.py      ← nearby search
│   ├── core/
│   │   ├── config.py      ← pydantic-settings (.env loader)
│   │   ├── security.py    ← bcrypt + JWT
│   │   └── redis.py       ← async Redis client lifecycle
│   ├── database/
│   │   ├── base.py        ← SQLAlchemy Base
│   │   └── connection.py  ← engine + get_db dependency
│   ├── models/
│   │   ├── user.py
│   │   ├── user_location.py
│   │   └── location_history.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── location.py
│   │   └── places.py
│   ├── repositories/
│   │   ├── location_repository.py
│   │   └── redis_repository.py
│   ├── services/
│   │   ├── location_service.py
│   │   └── places_service.py
│   ├── integrations/
│   │   └── google_places.py
│   ├── dependencies/
│   │   ├── auth.py
│   │   └── places.py
│   ├── exceptions/
│   │   ├── custom_exceptions.py
│   │   └── places.py
│   ├── validators/
│   │   └── location_validator.py
│   ├── utils/
│   │   └── response.py
│   └── main.py
├── .env                   ← fill in your values
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL running locally (via pgAdmin or CLI)
- Docker Desktop installed and running

---

### 2. Clone / unzip the project

```bash
cd geo-map-backend
```

---

### 3. Create virtual environment

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

---

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 5. Create PostgreSQL database

Open pgAdmin or use psql:

```sql
CREATE DATABASE geomapdb;
```

---

### 6. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/geomapdb
SECRET_KEY=your-super-secret-key-minimum-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

GOOGLE_PLACES_API_KEY=your_google_places_api_key_here
GOOGLE_PLACES_BASE_URL=https://places.googleapis.com/v1

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_CACHE_TTL=3600
```

> **Google API Key note:** In Google Cloud Console, enable **Places API (New)** — not the legacy Places API. The endpoint `POST /v1/places:searchNearby` only works with the New API.

---

### 7. Start Redis via Docker

```bash
docker-compose up -d
```

Verify Redis is running:

```bash
docker exec -it geo_redis redis-cli ping
# Expected: PONG
```

Redis Insight UI: `http://localhost:5540`

---

### 8. Run Alembic migrations

```bash
# Generate migration (detects all 3 models automatically)
alembic revision --autogenerate -m "initial tables: users, user_locations, location_history"

# Apply to database
alembic upgrade head
```

Verify in pgAdmin: `geomapdb → Schemas → public → Tables`
You should see: `users`, `user_locations`, `location_history`

---

### 9. Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected startup output:
```
INFO | app.core.redis | Redis connection established at localhost:6379
INFO | app.main       | geo-map-backend ready.
INFO | uvicorn        | Application startup complete.
```

Swagger UI: `http://localhost:8000/docs`
ReDoc: `http://localhost:8000/redoc`

---

## API Reference

### Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/signup` | No | Register new user |
| POST | `/api/v1/auth/login` | No | Login, returns Bearer token |
| POST | `/api/v1/auth/logout` | Yes | Logout |
| GET | `/api/v1/auth/me` | Yes | Get current user profile |

### Location Management

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/locations/gps` | Yes | Auto GPS location update |
| PUT | `/api/v1/locations/manual` | Yes | Manual location update |
| GET | `/api/v1/locations/me` | Yes | Get current active location |
| GET | `/api/v1/locations/latest` | Yes | Get latest location record |
| GET | `/api/v1/locations/history` | Yes | Paginated location history |
| DELETE | `/api/v1/locations/current` | Yes | Soft-delete current location |

### Nearby Places

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/places/nearby-search` | Yes | Search nearby places (auto-uses saved location) |

---

## API Usage Examples

### Signup

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"full_name": "Krishna", "email": "k@example.com", "password": "secret123"}'
```

### Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "k@example.com", "password": "secret123"}'
```

Set token:
```bash
TOKEN="<access_token_from_response>"
```

### GPS Location Update

```bash
curl -X POST http://localhost:8000/api/v1/locations/gps \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 26.2183, "longitude": 78.1828, "accuracy": 12.0}'
```

### Manual Location Update

```bash
curl -X PUT http://localhost:8000/api/v1/locations/manual \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 19.0760, "longitude": 72.8777, "metadata_notes": "Mumbai office"}'
```

### Nearby Places Search

```bash
curl -X POST http://localhost:8000/api/v1/places/nearby-search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"radius": 500, "max_result_count": 20}'
```

No coordinates needed — backend reads from user's saved location automatically.

---

## Redis Cache Inspection

```bash
# Enter Redis CLI
docker exec -it geo_redis redis-cli

# List all cached nearby searches
KEYS nearby:*

# Check TTL on a specific key
TTL nearby:15:26.2183:78.1828:500:20

# Inspect cached data
GET nearby:15:26.2183:78.1828:500:20

# Force fresh Google API call (bust cache)
DEL nearby:15:26.2183:78.1828:500:20
```

Redis Insight: `http://localhost:5540`
- Add database: Host `localhost`, Port `6379`
- Browse keys filtered by `nearby:*`

---

## Cache Key Format

```
nearby:{user_id}:{latitude}:{longitude}:{radius}:{max_result_count}

Example:
nearby:15:26.2183:78.1828:500:20
```

Different user, different location, or different radius = different cache entry.

---

## Business Rules

- One user has one active current location at a time (`is_current=True`)
- GPS and manual updates both deactivate the previous current record
- GPS duplicate suppression: pings within 10m are acknowledged but not persisted
- `location_history` is append-only — never updated or deleted
- user_id is always sourced from the JWT token, never from the request body
- Nearby search reads the latest active location automatically
- Cache TTL: 60 minutes per search parameter combination

---

## Git Commit Plan

```bash
git init
git add .gitignore requirements.txt docker-compose.yml alembic.ini
git commit -m "chore: project scaffold, dependencies, docker setup"

git add alembic/
git commit -m "chore: alembic migration environment"

git add app/core/ app/database/
git commit -m "feat(core): config, security, redis client, db session"

git add app/models/
git commit -m "feat(models): User, UserLocation, LocationHistory"

git add app/schemas/
git commit -m "feat(schemas): auth, location, places schemas"

git add app/exceptions/ app/validators/
git commit -m "feat: custom exceptions and coordinate validators"

git add app/repositories/
git commit -m "feat(repo): LocationRepository and RedisRepository"

git add app/integrations/
git commit -m "feat(integration): Google Places API (New) async client"

git add app/services/
git commit -m "feat(services): LocationService and PlacesService"

git add app/dependencies/
git commit -m "feat(deps): auth and places dependency injection"

git add app/utils/
git commit -m "feat(utils): standardised response builder"

git add app/api/ app/main.py
git commit -m "feat(api): auth, locations, places routes + FastAPI lifespan"
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Redis connection failed` | Run `docker-compose up -d` first |
| `Google Places API 403` | Enable **Places API (New)** in Google Cloud Console |
| `Google Places API 429` | Rate limit hit — wait or upgrade quota |
| `Could not validate credentials` | Token expired — login again |
| `User location not found` | Call `/api/v1/locations/gps` or `/manual` first |
| Alembic `Target database is not up to date` | Run `alembic upgrade head` |
| `psycopg2 connection refused` | Confirm PostgreSQL is running and DATABASE_URL is correct |

# 1. Stop & destroy everything (containers + volumes = clean slate)
docker compose down --remove-orphans --volumes

# 2. Build fresh image (no cache)
docker compose build --no-cache

# 3. Start all services
docker compose up -d

# 4. Verify all containers are up
docker compose ps

# 5. Confirm API connected to Redis
docker logs geo_api

# 6. Confirm RedisInsight registration
docker logs geo_redis_insight_init

# 7. Open RedisInsight in browser
#    → http://localhost:5540
#    → Connection "geo-map-redis" will already be there ✅

# 8. Open API docs
#    → http://localhost:8000/docs

