# 📖 GeoMap — System Workflow Explained

## Project Structure & Module Responsibilities

This document explains how each file/module works, how data flows between layers, and how the system behaves in different scenarios.

---

## 1. Architecture Overview

```
Client (HTTP/WS)
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  API Layer  ───  Dependency Injection  ───  Validation       │
│  (app/api/v1/)         (app/dependencies/)                   │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Service Layer (Business Logic)                              │
│  (app/services/)                                             │
└──────────────────────────────────────────────────────────────┘
    │                        │
    ▼                        ▼
┌─────────────────┐  ┌───────────────────────────┐
│  Repository     │  │  Integration Layer         │
│  Layer          │  │  (app/integrations/)       │
│  (app/repos/)   │  │   Google, OpenAI, Pinecone │
└─────────────────┘  └───────────────────────────┘
    │                        │
    ▼                        ▼
┌──────────────┐   ┌───────────────────────┐
│  PostgreSQL  │   │  Redis / External APIs │
└──────────────┘   └───────────────────────┘
```

---

## 2. Core Module Workflows

### 2.1 `app/main.py` — Application Entry Point

**What it does:** Initializes FastAPI app, sets up all middleware, creates HTTP client pools, registers routers, and starts background tasks.

**Workflow:**
```
1. Create FastAPI app with title "GeoMap"
2. Configure CORS (allow all origins in dev)
3. Initialize Rate Limiter (SlowAPI)
4. Lifespan (startup/shutdown):
   a. Create shared httpx.AsyncClient pools (50 max connections each):
      - http_places: for Google Places API
      - http_text_search: for Google Text Search
      - http_place_details: for Place Details API
      - http_routes: for Google Routes API
      - http_weather: for Open-Meteo (free, no key needed)
   b. Initialize OpenAI client (async HTTP)
   c. Initialize Pinecone client (async gRPC with thread pool)
   d. Register all API routers
5. Add global exception handlers (catch-all returns 500 JSON)
```

**Key Files Imported:**
- All routers from `app/api/v1/`
- `Limiter` from SlowAPI
- `httpx` for async HTTP client pools

---

### 2.2 `app/core/config.py` — Settings

**What it does:** Loads all configuration from environment variables using Pydantic v2.

**Workflow:**
```
1. Reads .env file (or .env.docker in container )
2. Validates required secrets (SECRET_KEY, GOOGLE_PLACES_API_KEY, etc.)
3. Validates DATABASE_URL format (must be PostgreSQL)
4. Exposes `settings` singleton
```

**Key Settings:**
| Setting | Default | Purpose |
|---------|---------|---------|
| ACCESS_TOKEN_EXPIRE_MINUTES | 60 | JWT access token lifetime |
| REFRESH_TOKEN_EXPIRE_DAYS | 7 | JWT refresh token lifetime |
| REDIS_DETAILS_CACHE_TTL | 86400 | Place details cache (24h) |
| DETAILS_STALE_AFTER_DAYS | 7 | Re-fetch from Google after 7 days |
| MAX_SESSIONS_PER_USER | 100 | Max simultaneous Q&A sessions |

---

### 2.3 `app/core/security.py` — JWT Tokens

**What it does:** Creates and validates JWT access/refresh tokens with audience separation.

**Workflow:**
```
CREATE ACCESS TOKEN:
  data + type="access" + exp (1h) + iat + aud="geo-map-access"
  → HS256 sign with SECRET_KEY → JWT string

DECODE ACCESS TOKEN:
  JWT → verify signature + exp + aud="geo-map-access"
  → reject if type != "access" (prevents refresh token misuse)
  → return payload or None

CREATE REFRESH TOKEN:
  Same pattern with type="refresh", aud="geo-map-refresh", 7-day expiry
```

**Security Features:**
- Audience separation (access vs refresh have different `aud` claims)
- Type check prevents using a refresh token as an access token
- HS256 signing with secret key

---

### 2.4 `app/database/connection.py` — Database Session

**What it does:** Creates SQLAlchemy engine, session factory, and provides `get_db` dependency.

**Workflow:**
```
1. Create engine: `create_async_engine(DATABASE_URL, pool_size=10, max_overflow=20)`
2. Create session factory: `sessionmaker(bind=engine)`
3. FastAPI dependency `get_db()`:
   → yield session
   → close() after request completes (even on errors)
```

**Key Points:**
- Pool size: 10 connections, 20 overflow (max 30)
- Connection recycle: 3600 seconds
- `pool_pre_ping=True` (test connection before using)

---

### 2.5 `app/core/redis.py` — Redis Client

**What it does:** Creates and provides Redis client instance.

**Workflow:**
```
1. On startup: create aioredis.Redis connection
2. Graceful degradation: if Redis is unavailable, return None
3. Used by:
   - TokenBlacklistService (blacklisted tokens)
   - OTPService (pending registrations)
   - All cache operations (search, details, routes)
```

**Graceful Degradation Behavior:**
- If Redis is down, all cache reads return None (cache miss → fetch fresh)
- Token blacklisting returns False (fail open → token allowed)
- Stampede lock returns True (allow direct Google call)

---

### 2.6 `app/integrations/google_place_details.py` — Google Place Details Client

**What it does:** Calls Google Places API (New) `GET /v1/places/{place_id}` with a field mask.

**Workflow:**
```
1. Build URL: {base_url}/places/{place_id}
2. Build headers: X-Goog-Api-Key, X-Goog-FieldMask
3. GET request via shared httpx client (or create one per call)
4. Handle responses:
   - 200 → Parse into PlaceDetailResult (opening hours, photos, reviews)
   - 404 → Raise PlaceDetailNotFoundError (mapped to HTTP 404)
   - 400 with "not found" → Raise PlaceDetailNotFoundError
   - 429 → Raise GooglePlacesRateLimitError (HTTP 429)
   - 403 → Raise GooglePlacesAPIError (check API key)
   - Other 4xx/5xx → Raise GooglePlacesAPIError with Google's error message
5. Parse response into structured PlaceDetailResult:
   - Opening hours (periods, weekday descriptions)
   - Photos (name, dimensions)
   - Reviews (author, rating, text)
   - Amenities (dine-in, takeout, parking, wheelchair access)
   - Extended data (EV charging, payment, address components)
```

**Field Mask (cost control):**
```
id, displayName, formattedAddress, location, types, primaryType,
businessStatus, currentOpeningHours, regularOpeningHours,
regularSecondaryOpeningHours, internationalPhoneNumber,
nationalPhoneNumber, websiteUri, googleMapsUri, rating,
userRatingCount, priceLevel, editorialSummary, photos, reviews,
accessibilityOptions, parkingOptions, paymentOptions, dineIn,
takeout, delivery, curbsidePickup, reservable, servesBreakfast,
servesLunch, servesDinner, servesBeer, servesWine, servesCocktails,
outdoorSeating, liveMusic, goodForChildren, goodForGroups,
restroom, allowsDogs, utcOffsetMinutes, plusCode,
addressComponents, evChargeOptions, subDestinations
```

---

### 2.7 `app/services/place_details_service.py` — Place Details Service

**What it does:** Orchestrates 3-tier caching and Google API calls for place details.

**Workflow:**
```
get_place_details(place_id):
  │
  ├── Tier 1: Redis Cache
  │   Attempt: redis_repo.get(key)
  │   HIT → return PlaceDetailResult + source="redis"
  │   MISS → continue
  │
  ├── Tier 2: PostgreSQL
  │   Attempt: repo.get_by_place_id(place_id)
  │   HIT:
  │     Check staleness (last_fetched > 7 days?)
  │       Fresh → return PlaceDetailResult + source="database"
  │       Stale → fall through to Google (save display_name for fallback)
  │   MISS → continue
  │
  └── Tier 3: Google Places API (with stampede lock)
      Attempt: _acquire_lock(place_id) via Redis SET NX EX 30
      ├── Lock acquired:
      │   ├── Re-check cache (TOCTOU mitigation)
      │   ├── Call Google Place Details API
      │   ├── Save to PostgreSQL (repo.upsert)
      │   ├── Write to Redis cache (24h TTL)
      │   ├── Trigger background knowledge sync (Pinecone vectors)
      │   └── Release lock
      ├── Lock NOT acquired (another request is fetching):
      │   ├── Wait up to 3s (10 retries × 300ms)
      │   ├── Check cache after each retry
      │   └── Fall through to Google if all retries timeout
      └── Return PlaceDetailResult + source="google"
```

**Background Knowledge Sync:**
After a successful Google fetch, a fire-and-forget async task creates Pinecone vectors:
```
_sync_task():
  1. Create new DB session (request session is closed)
  2. Call KnowledgeService.sync_place_knowledge()
  3. Build document → Embed with OpenAI → Upsert to Pinecone
  4. Mark place as knowledge_synced = True
  5. Log success or failure (never crashes the request)
```

**Error Handling:**
- Redis unavailable → skip cache, call Google directly
- Lock acquire fails → proceed without lock
- Google API error → propagate to API layer (HTTP 4xx/5xx)
- Background sync failure → log warning, response is already returned

---

### 2.8 `app/services/place_qa_service.py` — Place Q&A Service

**What it does:** AI-powered question answering about specific places using RAG.

**Workflow:**
```
answer_question(place_id, request, user_id):
  │
  ├── Step 0: Credit Check
  │   Check if user has ≥ 5 credits
  │   Insufficient → raise HTTP 402
  │
  ├── Step 1: Session Management
  │   session_id provided?
  │   ├── Yes → Load existing session + last 10 messages
  │   ├── No  → Create new session (max 100 per user)
  │
  ├── Step 2: Load Place from DB
  │   Not in DB → raise PlaceDetailNotFoundError
  │
  ├── Step 3: Check Knowledge Sync State
  │   sync_record.sync_status == "synced"?
  │   ├── Yes → knowledge_available = True (Pinecone has vectors)
  │   └── No  → knowledge_available = False (structured data only)
  │
  ├── Step 4: Embed Question (if knowledge available)
  │   Call OpenAI embeddings API
  │   Fail → fall back to structured_only
  │
  ├── Step 5: Query Pinecone (if embedding succeeded)
  │   Query by place_id namespace, top_k results
  │   Fail → empty matches, structured_only fallback
  │
  ├── Step 6: Filter by Similarity Threshold (≥ 0.30)
  │   Sort by score, filter low-quality matches
  │
  ├── Step 7: Build Context
  │   1. Conversation history (last 10 messages)
  │   2. Structured facts block (name, address, hours, reviews)
  │   3. Pinecone chunks (token-budgeted to 3000 total)
  │
  ├── Step 8: System Prompt Assembly
  │   Anti-hallucination prompt + context block
  │
  ├── Step 9: Call OpenAI Chat Completions
  │   GPT-4o-mini, temperature 0.7, max 800 tokens
  │
  └── Step 10: Persist
      1. Deduct 5 credits (atomic with message save)
      2. Save user + assistant messages
      3. Update session timestamp
      4. Commit (all or nothing)
      5. Best-effort audit log (separate commit)
```

**Answer Sources:**
| Source | Meaning | When Used |
|--------|---------|-----------|
| `rag` | Full RAG: structured + Pinecone | Knowledge synced + quality matches found |
| `structured_only` | Only structured facts | Knowledge synced but no good matches |
| `fallback` | No structured data | Knowledge not available (fallback prompt) |

---

### 2.9 `app/services/discovery_service.py` — Discovery Service

**What it does:** Orchestrates text search, nearby search, and autocomplete with caching.

**Workflow:**
```
text_search(request, user_id):
  1. Resolve location bias (explicit or user's saved location)
  2. Build cache key: SHA256(text_query + bias + params)
  3. Check Redis cache → HIT → return cached
  4. MISS → Call Google Text Search API
  5. Write to Redis cache (1 hour TTL)
  6. Audit log to PostgreSQL (search_queries + search_results)
  7. Return results

nearby_search(request, user_id):
  1. Load user's current location (required)
  2. Resolve preset/types (preferred_types or famous_places)
  3. Build cache key
  4. Check Redis → HIT/MISS → same pattern as text_search
  5. Call Google Nearby Search API

autocomplete(input, ...):
  1. Resolve location bias
  2. Build cache key (shorter TTL: 5 minutes)
  3. Check Redis → HIT/MISS
  4. Call Google Autocomplete API
  5. Return predictions

discovery_search(request):
  1. Auto-detect mode from query text:
     - Contains "near me", "nearby", "around" → nearby mode
     - Otherwise → text mode
  2. Delegate to text_search or nearby_search
```

---

### 2.10 `app/services/ai_chat_service.py` — AI Chat Service

**What it does:** General AI travel assistant with conversation history.

**Workflow:**
```
chat_message(query, user_id, session_id):
  1. Credit check (5 credits)
  2. Session management (create/continue)
  3. Load conversation history (last 10 messages)
  4. Check token budget (2000 tokens max)
  5. Truncate oldest messages if over budget
  6. Build system prompt (travel assistant role)
  7. Call OpenAI chat completions
  8. Persist messages + deduct credits (atomic)
  9. Return reply
```

---

### 2.11 `app/services/routes_service.py` — Routes Service

**What it does:** Computes routes and route matrices using Google Routes API.

**Workflow:**
```
compute_route(request, user_id):
  1. Load user's current location (origin)
  2. Resolve destination from place_id or lat/lon
  3. Build route request:
     - origin = user's location
     - destination = resolved
     - waypoints (up to 25)
     - travel_mode (DRIVE/WALK/BICYCLE/TWO_WHEELER)
     - routing_preference (TRAFFIC_AWARE/UNAWARE)
     - route modifiers (avoid tolls, highways, ferries)
  4. Check Redis cache (5 min TTL)
  5. MISS → Call Google computeRoutes API
  6. Parse response:
     - distance, duration, traffic delay
     - encoded polyline
     - turn-by-turn steps with instructions
  7. Cache and return

compute_route_matrix(request, user_id):
  1. Same origin resolution
  2. Multiple destinations
  3. Call computeRouteMatrix API
  4. Return ETAs for all destinations
```

**Travel Mode Behavior:**
| Mode | Traffic Support | Notes |
|------|----------------|-------|
| DRIVE | ✅ TRAFFIC_AWARE | Real-time traffic data |
| WALK | ❌ TRAFFIC_UNAWARE | Pedestrian routes |
| BICYCLE | ❌ TRAFFIC_UNAWARE | Cycling routes |
| TWO_WHEELER | ❌ TRAFFIC_UNAWARE | Motorcycle routes |
| TRANSIT | ❌ TRAFFIC_UNAWARE | Public transit |

---

### 2.12 `app/services/weather_service.py` — Weather Service

**What it does:** Fetches weather forecast and air quality from Open-Meteo (free API, no key required).

**Workflow:**
```
get_forecast(user_id, start_date, end_date):
  1. Load user's current location
  2. No location → raise UserLocationNotFoundError
  3. Call Open-Meteo API:
     - URL: https://api.open-meteo.com/v1/forecast
     - Params: latitude, longitude, hourly, daily, current_weather
     - Units: Celsius, km/h
  4. Return raw JSON (parsed by API layer)

get_air_quality(user_id, start_date, end_date):
  Same pattern with different Open-Meteo endpoint
```

**Rate Limiting:** 10/minute on both endpoints (added via SlowAPI).

---

### 2.13 `app/services/auth_service.py` — Authentication Services

**What it does:** Manages OTP generation/verification, token blacklisting, and email sending.

**Component Files:**

**`app/services/otp_service.py`** — OTP Management:
```
store_pending_registration(email, full_name, hashed_password):
  1. Generate 6-digit OTP (random.randint(100000, 999999))
  2. Store in Redis: otp:pending:{email} → {otp, full_name, hashed, attempts=0}
  3. TTL: 120 seconds (2 minutes)
  4. Return OTP

verify_and_consume(email, submitted_otp):
  1. Atomic Lua script:
     - Load registration data from Redis
     - Check attempts < 5
     - Verify OTP matches
     - Delete key on success
     - Increment attempts on failure
  2. Return reg_data on success, None on failure
```

**`app/services/token_blacklist_service.py`** — Token Blacklisting:
```
blacklist_token(token):
  1. Extract token expiration from JWT claims
  2. Calculate TTL (capped at 3600 seconds)
  3. Store in Redis: token:blacklist:{token} → "1" with TTL
  4. Redis down → log warning, return False

is_token_blacklisted(token):
  1. Check if key exists in Redis
  2. Redis down → return False (fail open)
```

---

### 2.14 `app/schemas/` — Pydantic Schemas

**What it does:** Defines request/response models and validation for all API endpoints.

**Key Schemas:**

| Schema File | Contains |
|-------------|----------|
| `auth.py` | SignupRequest, LoginRequest, TokenResponse, UserResponse |
| `location.py` | GPSLocationRequest, ManualLocationRequest, LocationResponse |
| `discovery.py` | TextSearchRequest, NearbyDiscoveryRequest, DiscoveryPlaceResult |
| `place_details.py` | PlaceDetailResult, OpeningHours, PlacePhoto, PlaceReview |
| `place_qa.py` | PlaceQuestionRequest, PlaceQuestionResponse, GroundingFragment |
| `routes.py` | RouteRequest, RouteMatrixRequest, RouteResult |
| `weather.py` | WeatherRequest, WeatherForecastResponse, AirQualityResponse |
| `ai_chat.py` | ChatMessageRequest, ChatResponse |
| `saved_places.py` | SavePlaceRequest, SavePlaceActionResponse |
| `visits.py` | VisitRequest, VisitResponse |
| `comparison.py` | ComparisonRequest, ComparisonResult |
| `knowledge.py` | KnowledgeSyncRequest, KnowledgeSyncResponse |

---

### 2.15 `app/repositories/` — Data Access Layer

**What it does:** All database CRUD operations. Each repository wraps a SQLAlchemy model.

| Repository | Model | Key Operations |
|------------|-------|----------------|
| `user_repository.py` | User | get_by_email, get_by_id, create, create_local_user_verified |
| `location_repository.py` | UserLocation | upsert_current, get_current, get_history, get_latest |
| `search_repository.py` | SearchQuery, SearchResult | create search + results |
| `place_details_repository.py` | PlaceDetail | upsert, get_by_place_id, mark_knowledge_synced |
| `knowledge_repository.py` | PlaceKnowledgeSync | upsert_sync_record, get_sync_record, mark_failed |
| `place_qa_repository.py` | PlaceQASession, PlaceQAMessage | sessions CRUD, messages CRUD |
| `ai_chat_repository.py` | AIChatSession, AIChatMessage | sessions CRUD, messages CRUD |
| `saved_place_repository.py` | UserSavedPlace | CRUD + search |
| `visit_repository.py` | PlaceVisitLog | CRUD + stats |

| `redis_repository.py` | (Redis) | get, set, delete with TTL |

---

## 3. API Layer — Router Details

### 3.1 Router Registration (app/api/v1/__init__.py)

```python
routers = [
    auth.router,           # /api/v1/auth/*
    locations.router,      # /api/v1/locations/*
    discovery.router,      # /api/v1/discovery/*
    place_details.router,  # /api/v1/places/*/details
    place_qa.router,       # /api/v1/places/qa/*
    ai_chat.router,        # /api/v1/chat/*
    routes.router,         # /api/v1/routes/*
    weather.router,        # /api/v1/weather/*
    comparison.router,     # /api/v1/comparison
    saved_places.router,   # /api/v1/places/{id}/save, /api/v1/places/saved/*
    visits.router,         # /api/v1/places/{id}/visit, /api/v1/visits/*
    ws.router,             # /api/v1/ws/chat (WebSocket)
    knowledge.router,      # /api/v1/places/*/knowledge-sync (internal)
]
```

### 3.2 Router Details

| File | Router Prefix | Endpoints | Auth |
|------|---------------|-----------|------|
| `auth.py` | /auth | signup, verify-otp, login, refresh, logout, me | Mixed (some public) |
| `locations.py` | /locations | GPS, manual, current, history, latest | Bearer |
| `discovery.py` | /discovery | search, nearby, autocomplete | Bearer |
| `place_details.py` | /places | /{id}/details | Bearer |
| `place_qa.py` | /places/qa | sessions, question, session CRUD | Bearer |
| `ai_chat.py` | /chat | message | Bearer |
| `routes.py` | /routes | compute, matrix | Bearer |
| `weather.py` | /weather | forecast, air-quality | Bearer |
| `comparison.py` | /comparison | (POST) | Bearer |
| `saved_places.py` | /places/{id}/save, /places/saved | CRUD, nearby | Bearer |
| `visits.py` | /places/{id}/visit, /visits | CRUD, stats | Bearer |
| `ws.py` | /ws | chat (WebSocket) | Bearer (first msg) |
| `knowledge.py` | /places/{id}/knowledge-sync | sync (internal) | Bearer |

---

## 4. WebSocket Workflow

### 4.1 Connection Lifecycle

```
1. Client connects to ws://localhost:8000/ws/chat
   → Server accepts immediately (no auth yet)
   → Stored in ConnectionManager with pending_auth flag

2. Client sends auth message:
   {"type": "auth", "token": "Bearer eyJ..."}
   → Server decodes JWT, validates signature + expiry
   → Valid → Set user_id, remove pending_auth flag
          → Send: {"type": "connected", "user_id": 1}
   → Invalid → Send: {"type": "error", "message": "authentication failed"}
            → Close connection

3. Client sends messages:
   → "chat_message": General AI chat
   → "place_question": Place-specific Q&A

4. Server streams responses token-by-token:
   → {"type": "metadata", "session_id": "...", "is_new_session": true}
   → {"type": "token", "content": "Here's the "}
   → {"type": "token", "content": "answer..."}
   → {"type": "done", "title": "...", "metadata": {...}}

5. Idle timeout (5 minutes):
   → No messages received → Server sends close frame
   → Connection cleaned up from ConnectionManager
```

### 4.2 ConnectionManager Thread Safety

```python
class ConnectionManager:
    def __init__(self):
        self._lock = asyncio.Lock()   # Protects all dict operations
        self._connections = {}         # user_id → list of WebSocket
        self._pending_auth = {}        # WebSocket → pending_auth flag

    async def connect(self, websocket):
        async with self._lock:
            # Store connection with pending_auth = True

    async def disconnect(self, websocket):
        async with self._lock:
            # Remove from all dicts, close if not already closed

    async def authenticate(self, websocket, user_id):
        async with self._lock:
            # Set user_id, remove pending_auth flag

    async def broadcast_to_user(self, user_id, message):
        async with self._lock:
            # Send to all connections for this user
```

---

## 5. Knowledge Sync Workflow

### 5.1 `app/services/knowledge_service.py` — Knowledge Sync Service

**What it does:** Builds a knowledge document from place data, embeds it, and stores vectors in Pinecone.

**Workflow:**
```
sync_place_knowledge(place_id, request):
  │
  ├── Step 1: Load Place from DB
  │   Not found → raise PlaceDetailNotFoundError
  │
  ├── Step 2: Build Document Sections
  │   build_place_document(place) → Dict[str, str]:
  │   - summary: name + address + coordinates
  │   - category: primary_type + all types
  │   - hours: opening hours with weekday descriptions
  │   - contact: phone, website, maps URI
  │   - ratings: rating, review count, price level, status
  │   - accessibility: wheelchair info
  │   - amenities: dining, food, atmosphere, parking, payment, EV
  │   - reviews: up to 5 reviews with author + rating
  │
  ├── Step 3: Compute Source Version
  │   SHA-256 of all concatenated sections → change detection
  │
  ├── Step 4: Skip Check (Idempotency)
  │   force_resync=False + existing + synced + same version?
  │   → SKIP, return "already up to date"
  │
  ├── Step 5: Delete Stale Vectors
  │   Delete all vectors in place_id namespace from Pinecone
  │
  ├── Steps 6-7: Build Chunks
  │   Each section → one chunk (max 3000 chars)
  │
  ├── Step 8: Embed All Chunks
  │   Batch call to OpenAI embeddings API
  │   Fail → mark_failed, raise
  │
  ├── Step 9: Build Pinecone Vector Dicts
  │   Each vector: id, values (embedding), metadata (place_id, section, text)
  │
  ├── Step 10: Upsert to Pinecone
  │   Upload all vectors → get upserted_count
  │   Fail → mark_failed, raise
  │
  └── Step 11-13: Persist State
      Save sync_record to DB (synced, vector_count, namespace)
      Mark place_details.knowledge_synced = True
      Commit
```

---

## 6. Authentication Flow (Complete)

### 6.1 Registration Flow

```
User → POST /auth/signup {email, password, full_name}
  │
  ├── Validate email not taken (409 if exists)
  ├── Hash password (bcrypt)
  ├── Store in Redis: otp:pending:{email} → {otp, full_name, hash}
  ├── Send OTP email (via SMTP / Mailpit in dev)
  └── Return {message, email, expires_in}
      │
      ▼   (user checks email for 6-digit OTP)
      │
User → POST /auth/verify-otp {email, otp}
  │
  ├── Atomic Lua script in Redis:
  │   • Load registration data
  │   • Check attempts < 5
  │   • Verify OTP
  │   • Delete key
  │   • Return success/failure
  ├── Create user in PostgreSQL (email_verified = true)
  ├── Issue access_token (1h) + refresh_token (7d)
  └── Return tokens + user profile
```

### 6.2 Token Refresh Flow

```
User → POST /auth/refresh {refresh_token}
  │
  ├── Step 1: Check Redis blacklist (fast-fail)
  │   Blacklisted → 401 "Token revoked"
  │
  ├── Step 2: Decode + verify refresh_token
  │   Invalid/expired → 401 "Invalid token"
  │
  ├── Step 3: Load user from DB
  │   Not found/inactive → 401
  │
  ├── Step 4: Issue new token pair FIRST
  │   (If server crashes here, old token still valid)
  │
  └── Step 5: Blacklist old refresh token
      (Rotation complete, old token single-use)
```

### 6.3 Logout Flow

```
User → POST /auth/logout {refresh_token?}
  │
  ├── Blacklist access token (from Authorization header)
  └── If refresh_token provided → Blacklist it too
      Both tokens now invalid
```

---

## 7. Caching Architecture

### 7.1 Cache Hierarchy

```
                    ┌─────────────┐
                    │   Request   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Redis      │ ← Fastest, TTL-based
                    │  (Layer 1)  │
                    └──────┬──────┘
                     HIT   │   MISS
                    ┌──────┘
                    │       ┌──────▼──────┐
                    │       │ PostgreSQL  │ ← Slower, persistent
                    │       │ (Layer 2)   │
                    │       └──────┬──────┘
                    │        HIT   │   MISS
                    │       ┌──────┘
                    │       │       ┌──────▼──────┐
                    │       │       │ Google API  │ ← Slowest, external
                    │       │       │ (Layer 3)   │
                    │       │       └─────────────┘
                    ▼       ▼
               Return Result
```

### 7.2 Cache TTLs

| Data Type | Redis TTL | PG Fallback |
|-----------|-----------|-------------|
| Place Search | 1 hour | N/A |
| Place Details | 24 hours | 7 days before re-fetch |
| Routes | 5 minutes | N/A |
| Route Matrix | 2 minutes | N/A |
| Autocomplete | 5 minutes | N/A |

### 7.3 Stampede Protection

When multiple requests fetch the same place simultaneously:
```
Request A ──→ Acquire Redis Lock (SET NX EX 30) → SUCCESS
                → Fetch from Google
                → Write to cache
                → Release lock
                
Request B ──→ Acquire Redis Lock → FAIL (A has it)
                → Wait 300ms → Check cache → MISS
                → Wait 300ms → Check cache → MISS
                → ... (up to 10 retries / 3 seconds)
                → After 3 seconds, also fetch from Google
```

---

## 8. Error Handling Across Layers

### 8.1 Exception Hierarchy

```
app/exceptions/
├── custom_exceptions.py
│   ├── NotFoundError (404)
│   ├── BadRequestError (400)
│   └── ConflictError (409)
├── places.py
│   ├── GooglePlacesAPIError (502)
│   ├── GooglePlacesRateLimitError (429)
│   ├── GooglePlacesTimeoutError (504)
│   ├── PlaceDetailNotFoundError (404)
│   └── UserLocationNotFoundError (404)
└── open_meteo.py
    └── OpenMeteoAPIError (502)
```

### 8.2 Global Exception Handlers (in main.py)

```
@app.exception_handler(Exception)
→ Log to crashes.log with traceback
→ Return 500 JSON: {"detail": "Internal server error"}

@app.exception_handler(RequestValidationError)
→ Return 422 JSON with field-level error details
```

---

## 9. Data Flow for Key User Journeys

### 9.1 "Find places near me and ask about one"

```
1. POST /auth/login → Get JWT token
   └── auth.py → UserRepository → PostgreSQL → JWT issued

2. POST /locations/gps → Set current location
   └── locations.py → LocationService → LocationRepository → PostgreSQL

3. POST /discovery/nearby → Find nearby restaurants
   └── discovery.py → DiscoveryService → GooglePlacesClient
       → Redis check → Google API → Redis write → Audit log

4. GET /places/{place_id}/details → Get place info
   └── place_details.py → PlaceDetailsService
       → Redis check → PostgreSQL check → Google API
       → Save → Trigger knowledge sync → Return

5. POST /places/{place_id}/question → Ask about it
   └── place_qa.py → PlaceQAService
       → Credit check → Session mgmt → Load place
       → Embed → Pinecone query → Build context
       → OpenAI → Save messages → Return answer
```

### 9.2 "Plan a route and check weather"

```
1. POST /routes/compute → Get directions with traffic
   └── routes.py → RoutesService → GoogleRoutesClient
       → Redis check → Google API → Parse → Return

2. POST /weather/forecast → Check weather
   └── weather.py → WeatherService → OpenMeteoClient
       → Free API (no key) → Return
```

---

## 10. File Responsibility Summary

| File | Layer | Responsibility | Key Dependencies |
|------|-------|---------------|------------------|
| `main.py` | Entry | App init, middleware, lifespan | All routers, httpx |
| `core/config.py` | Config | Environment settings | .env file |
| `core/security.py` | Core | JWT creation/validation | python-jose |
| `core/redis.py` | Core | Redis client | aioredis |
| `core/websocket_manager.py` | Core | WS connection management | asyncio.Lock |
| `database/connection.py` | DB | Engine + session factory | SQLAlchemy |
| `integrations/google_places.py` | Integration | Nearby Search API | httpx |
| `integrations/google_text_search.py` | Integration | Text Search API | httpx |
| `integrations/google_place_details.py` | Integration | Place Details API | httpx |
| `integrations/google_autocomplete.py` | Integration | Autocomplete API | httpx |
| `integrations/google_routes.py` | Integration | Routes API | httpx |
| `integrations/openai_client.py` | Integration | Chat + Embeddings | httpx |
| `integrations/pinecone_client.py` | Integration | Vector DB | pinecone |
| `integrations/open_meteo.py` | Integration | Weather + Air Quality | httpx |
| `services/discovery_service.py` | Service | Search orchestration + cache | repos, integrations |
| `services/place_details_service.py` | Service | 3-tier detail fetch | repos, integrations |
| `services/place_qa_service.py` | Service | RAG question answering | repos, integrations |
| `services/ai_chat_service.py` | Service | General AI chat | repos, integrations |
| `services/routes_service.py` | Service | Route computation | repos, integrations |
| `services/weather_service.py` | Service | Weather fetch | repos, integrations |
| `services/knowledge_service.py` | Service | Pinecone sync | repos, integrations |
| `repositories/*.py` | Data | DB CRUD operations | SQLAlchemy models |
| `schemas/*.py` | Schema | Request/response models | Pydantic |
| `api/v1/*.py` | API | HTTP endpoints | services, dependencies |
| `dependencies/*.py` | DI | Service injection | FastAPI Depends |
| `models/*.py` | Model | SQLAlchemy ORM | SQLAlchemy |

---

> **Note:** The existing docs (PRD.md, TRD.md, Architecture.md, Database.md, API_Reference.md, Decision.md, Change.md, Task.md) contain additional details about product requirements, technical decisions, database schema, and project status. See those files for complementary information.
