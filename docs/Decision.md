# 🎯 Key Technical Decisions

## GeoMap — Location-Based Discovery Platform

---

## Decision 1: FastAPI over Django/Flask

**Context:** Choosing a Python web framework for a real-time location platform.

**Decision:** FastAPI with async support.

**Rationale:**
- Native async/await for WebSocket streaming and concurrent HTTP requests
- Automatic OpenAPI/Swagger documentation generation
- Pydantic v2-based request validation (compile-time type checking)
- Dependency Injection system cleanly separates concerns
- Superior performance (Starlette/uvicorn) vs Django/Flask

**Trade-offs:**
- Smaller ecosystem than Django (but all needed libraries exist)
- No built-in admin panel (not needed for this project)
- Less opinionated — requires more architectural discipline

---

## Decision 2: Custom JWT Auth instead of Clerk

**Context:** Original implementation used Clerk for authentication.

**Decision:** Switch to custom JWT with email/password + OTP.

**Rationale:**
- Full control over token format, expiry, and security
- No external dependency for auth (works offline)
- Refresh token rotation with Redis blacklist
- OTP email verification without third-party auth
- Cost savings (Clerk paid tier for production)
- JWT audience separation (access vs refresh tokens prevent misuse)

**Trade-offs:**
- More implementation work (security must be done right)
- Need to manage password hashing and OTP storage ourselves
- No social login out of the box

---

## Decision 3: Layered Architecture (Service + Repository)

**Context:** Organizing business logic and data access.

**Decision:** Separate Service layer and Repository layer.

**Rationale:**
- **Repositories** handle all database queries (single responsibility)
- **Services** contain business logic, orchestration, and error handling
- Clear separation makes unit testing possible (mock repositories)
- Changes to DB schema only affect repositories, not services
- Services are reusable across REST and WebSocket endpoints

**Example Flow:**
```
REST endpoint → Service.answer_question() → Repository.get_session()
                                    → Repository.create_message()
                                    → Integration.openai_client()
```

---

## Decision 4: SQLAlchemy ORM with Alembic

**Context:** Database access and schema management.

**Decision:** SQLAlchemy 2.0 ORM with Alembic migrations.

**Rationale:**
- Industry standard for Python PostgreSQL access
- Alembic provides version-controlled, reversible migrations
- 22 migration files covering all schema changes
- `synchronize_session='evaluate'` for bulk updates (performance + correctness)
- Window functions for pagination with total counts

---

## Decision 5: Redis for Multiple Purposes

**Context:** Need caching, OTP storage, token blacklist, and distributed locks.

**Decision:** Single Redis instance for all non-persistent state.

**Rationale:**
- Multi-purpose: caching (searches, details), state (OTP, blacklist), coordination (locks)
- Graceful degradation: app works without Redis, just slower
- All patterns are simple key-value with TTL — no complex data structures
- Redis Insight for visual monitoring (included in docker-compose)

**Redis Usage Breakdown:**
| Purpose | Key Pattern | TTL |
|---------|-------------|-----|
| Text Search | `text_search:{user_id}:{hash}` | 3600s |
| Nearby Search | `nearby:{user_id}:{lat}:{lon}:{radius}` | 3600s |
| Place Details | `place_details:{place_id}` | 86400s |
| Routes | `route:{user_id}:{mode}:{dest}` | 300s |
| Route Matrix | `route_matrix:{user_id}:{mode}:{hash}` | 120s |
| Autocomplete | `autocomplete:{user_id}:{hash}` | 300s |
| OTP Registration | `otp:pending:{email}` | 120s |
| Token Blacklist | `token:blacklist:{token}` | 3600s (capped) |
| Detail Fetch Lock | `place_details_lock:{place_id}` | 30s |

---

## Decision 6: RAG with Pinecone for Place Q&A

**Context:** Need to answer user questions about places with factual accuracy.

**Decision:** Retrieval-Augmented Generation with Pinecone vector database.

**Rationale:**
- **Reduces hallucinations:** Answers are grounded in actual place data
- **Structured facts + vector search:** Two-layer context (DB fields + Pinecone chunks)
- **Attribution:** Returns which source sections support each answer
- **Confidence scoring:** Average similarity score indicates reliability
- **Token budget management:** 3000 token limit, trimmed by oldest/lowest-scoring chunks
- **Idempotent sync:** Source version hash prevents redundant re-indexing

**RAG Pipeline Components:**
1. Structured facts (from PostgreSQL place_details)
2. Vector chunks (from Pinecone, scored by cosine similarity)
3. Conversation history (last 10 messages)
4. Strict system prompt (hallucination prevention checklist)

---

## Decision 7: WebSocket Streaming for AI Responses

**Context:** Users expect fast, real-time AI responses.

**Decision:** Dual-mode — REST for simple requests, WebSocket for streaming.

**Rationale:**
- WebSocket provides token-by-token streaming (200ms per token latency)
- Same service layer reused for both REST and WebSocket (no code duplication)
- Async generators yield tokens as they arrive from OpenAI
- 5-minute idle timeout prevents resource leaks
- Per-connection auth with JWT (not shared state)

**WebSocket Events:**
```
Client → {"type":"auth","token":"Bearer ..."}
Server → {"type":"connected","user_id":123}
Client → {"type":"chat_message","query":"Plan a trip","session_id":null}
Server → {"type":"metadata","session_id":"uuid","is_new_session":true}
Server → {"type":"token","content":"Here's my "}
Server → {"type":"token","content":"recommendation..."}
Server → {"type":"done","title":"Trip to Jaipur"}
```

---

## Decision 8: Concurrent Request Protection

**Context:** Multiple users can request the same place details simultaneously.

**Decision:** Redis-based distributed lock with retry.

**Rationale:**
- Prevents "thundering herd" on Google Places API (cost savings)
- First request acquires lock and fetches from Google
- Subsequent requests wait (max 10 retries × 300ms = 3 seconds)
- If lock holder finishes, cached result is returned to waiters
- If lock times out, fall through to Google (no denial of service)

**Similar patterns:**
- PostgreSQL unique constraint retry for location updates (race resolution)
- SQLAlchemy `synchronize_session='evaluate'` for stale object prevention
- Place Details upsert race recovery (IntegrityError → rollback → retry)

---

## Decision 9: Credit-Based AI Usage

**Context:** AI API calls cost money — need usage control.

**Decision:** Application-level credit system (50 free credits, 5 per AI call).

**Rationale:**
- `SELECT ... FOR UPDATE` row lock prevents race conditions on deduction
- Atomic commit: credits deducted in same transaction as message save
- Best-effort audit logging (never rolls back credit deduction)
- Graceful 402 Payment Required response with balance info

---

## Decision 10: Refresh Token Rotation (Safe Order)

**Context:** Token refresh must be secure but also reliable.

**Decision:** Issue new tokens FIRST, then blacklist old token.

**Rationale (Bug fix):**
- Original order: blacklist → issue. If server crashed between steps, user lost access permanently.
- New order: issue → blacklist. If server crashes, old token remains valid for retry.
- Security trade-off: old token remains valid microseconds longer, but blacklist runs immediately after.
- This is the standard OAuth2 pattern used by major providers.

---

## Decision 11: WSGI Server and Deployment

**Context:** Production deployment.

**Decision:** Uvicorn behind Docker, with docker-compose for local dev.

**Rationale:**
- Docker provides consistent environment across dev/prod
- docker-compose orchestrates PostgreSQL, Redis, Mailpit, and API
- Health checks ensure services start in correct order
- Redis Insight for visual cache monitoring
- Mailpit catches all outgoing emails in dev (no real email sending)
