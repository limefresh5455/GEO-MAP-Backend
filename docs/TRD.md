# 🔧 Technical Requirements Document (TRD)

## GeoMap — Location-Based Discovery Platform

**Version:** 3.0.0
**Date:** June 22, 2026

---

## 1. Technology Stack

### Backend
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Web Framework | FastAPI | 0.111.0 | REST API + WebSocket server |
| ASGI Server | Uvicorn | 0.29.0 | Production ASGI server |
| ORM | SQLAlchemy | 2.0.30 | Database ORM |
| Migration | Alembic | 1.13.1 | Schema migrations |
| Database | PostgreSQL | 16 | Primary data store |
| Cache | Redis | 7 | Caching, OTP, token blacklist |
| Auth | python-jose | 3.3.0 | JWT signing + verification |
| Password | bcrypt / passlib | 1.7.4 | Password hashing |

### AI & Embeddings
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| LLM | OpenAI GPT-4o-mini | — | Chat completions |
| Embeddings | OpenAI text-embedding-3-small | — | Vector embeddings |
| Vector DB | Pinecone | 4.1.0 | RAG knowledge storage |

### External APIs
| API | Purpose | Auth |
|-----|---------|------|
| Google Places API (New) | Text search, nearby search, place details, autocomplete | API Key |
| Google Routes API | Route computation, route matrix | API Key |
| Open-Meteo | Weather forecast, air quality | Free (no key) |
| OpenAI | Chat completions, embeddings | API Key |
| SMTP (Gmail) | OTP email delivery | App Password |

---

## 2. Project Structure

```
geo-map-updated/
├── app/
│   ├── api/v1/           # REST + WebSocket endpoints
│   │   ├── auth.py       # Registration, login, refresh, logout
│   │   ├── locations.py  # GPS + manual location CRUD
│   │   ├── discovery.py  # Text search, nearby, autocomplete
│   │   ├── place_details.py  # Place detail lookup
│   │   ├── routes.py     # Route computation + matrix
│   │   ├── place_qa.py   # Place Q&A sessions
│   │   ├── ai_chat.py    # General AI chat
│   │   ├── knowledge.py  # Knowledge sync trigger
│   │   ├── weather.py    # Weather forecast + air quality
│   │   └── ws.py         # WebSocket endpoint (streaming)
│   ├── core/             # Config, security, redis, websocket
│   ├── database/         # SQLAlchemy engine + session
│   ├── dependencies/     # FastAPI dependency injection
│   ├── exceptions/       # Custom HTTP exceptions
│   ├── integrations/     # External API clients
│   ├── models/           # SQLAlchemy ORM models
│   ├── repositories/     # Data access layer
│   ├── schemas/          # Pydantic request/response models
│   ├── services/         # Business logic layer
│   ├── utils/            # Helper utilities
│   └── validators/       # Validation logic
├── alembic/              # Database migrations (22 files)
├── docs/                 # Project documentation
├── docker-compose.yml    # Docker setup (PostgreSQL, Redis, Mailpit)
├── Dockerfile            # Container build file
└── requirements.txt      # Python dependencies
```

---

## 3. Architecture Pattern

### Layered Architecture

```
┌─────────────────────────────────────────────────┐
│                   Client                         │
│  (Web Frontend / Mobile / API Consumer)          │
└──────────────────┬──────────────────────────────┘
                   │ HTTP / WebSocket
                   ▼
┌─────────────────────────────────────────────────┐
│           API Layer (app/api/v1/)                │
│  ┌─────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ REST    │ │WebSocket │ │ Rate Limiter      │  │
│  │ Routes  │ │ Stream   │ │ (SlowAPI)         │  │
│  └────┬────┘ └────┬─────┘ └──────────────────┘  │
└───────┼───────────┼─────────────────────────────┘
        │           │
        ▼           ▼
┌─────────────────────────────────────────────────┐
│         Service Layer (app/services/)            │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Auth     │ │Discovery │ │ AI Chat / Q&A     │ │
│  │ Service  │ │ Service  │ │ Service           │ │
│  ├──────────┤ ├──────────┤ ├──────────────────┤ │
│  │ Routes   │ │ Weather  │ │ Place Details     │ │
│  │ Service  │ │ Service  │ │ Service           │ │
│  ├──────────┤ ├──────────┤ ├──────────────────┤ │
│  │ Credit   │ │ OTP      │ │ Token Blacklist   │ │
│  │ Service  │ │ Service  │ │ Service           │ │
│  └────┬─────┘ └────┬─────┘ └───────┬──────────┘ │
└───────┼────────────┼───────────────┼────────────┘
        │            │               │
        ▼            ▼               ▼
┌─────────────────────────────────────────────────┐
│       Repository Layer (app/repositories/)       │
│  Database access, CRUD operations, queries       │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ User     │ │ Location │ │ Search + Results  │ │
│  │ Repo     │ │ Repo     │ │ Repo              │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│      Integration Layer (app/integrations/)       │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Google   │ │ OpenAI   │ │ Pinecone         │ │
│  │ Places   │ │ Client   │ │ Client           │ │
│  ├──────────┤ ├──────────┤ ├──────────────────┤ │
│  │ Google   │ │ Open-    │ │                   │ │
│  │ Routes   │ │ Meteo    │ │                   │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────┘
```

---

## 4. Data Flow Patterns

### Request Flow (REST)
```
Client → FastAPI Router → Dependency Injection
  → Service Layer → Repository → Database
  → Service → Integration (external API if needed)
  → Response back to Client
```

### Streaming Flow (WebSocket)
```
Client → WebSocket Connect → JWT Auth
  → Message Loop (chat_message / place_question)
  → Service Layer → OpenAI Streaming
  → Token-by-token response via WebSocket
  → Persist messages + deduct credits
  → Done signal
```

### Cache Flow
```
Request → Check Redis Cache → HIT → Return cached
                                MISS → Check PostgreSQL
                                  → HIT → Update Redis → Return
                                  → MISS → Call Google API
                                    → Save to PG + Redis → Return
```

---

## 5. Security Architecture

### Authentication Flow
```
1. Signup → Email + Password → Hash password
   → Store in Redis (pending) → Send OTP email
2. Verify OTP → Check Redis (atomic Lua script)
   → Create user in PostgreSQL
   → Issue JWT pair (access + refresh)
3. Login → Verify password → Issue JWT pair
4. Protected Routes → Bearer token → Verify JWT
   → Check Redis blacklist → Load user → Proceed
5. Refresh → Verify refresh token signature + audience
   → Issue new token pair FIRST → Then blacklist old
6. Logout → Blacklist access token + refresh token
```

### Token Structure
```json
// Access Token (1 hour)
{
  "sub": "user_id",
  "type": "access",
  "aud": "geo-map-access",
  "exp": 1234567890,
  "iat": 1234567890
}

// Refresh Token (7 days)
{
  "sub": "user_id",
  "type": "refresh",
  "aud": "geo-map-refresh",
  "exp": 1234567890,
  "iat": 1234567890
}
```

---

## 6. Error Handling Strategy

| Layer | Strategy |
|-------|----------|
| API Router | Catch specific exceptions, log, re-raise HTTPException |
| Service | Raise custom exceptions (NotFoundError, BadRequestError, etc.) |
| Repository | Let SQLAlchemy errors propagate; handle specific constraint violations |
| Integration | Catch HTTP errors, raise typed exceptions (RateLimit, Timeout, APIError) |
| Global | Catch-all handler logs to crashes.log, returns 500 JSON |

---

## 7. Performance Optimization

- **Connection pooling**: httpx.AsyncClient pools (50 max connections per service)
- **Database pool**: 10 connections + 20 overflow, recycle at 3600s
- **Thread pool**: 4 workers for Pinecone (blocking I/O offloaded)
- **Redis caching**: 1 hour TTL for searches, 24 hours for place details
- **Stampede protection**: Redis lock for concurrent place detail fetches
- **Content-aware caching**: Only invalidate knowledge_synced when data changes
- **Token budget**: 3000 token limit for RAG context, truncate oldest history
