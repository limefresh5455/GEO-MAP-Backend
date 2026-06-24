# 🗄️ Database Schema

## GeoMap — Location-Based Discovery Platform

**Database:** PostgreSQL 16
**Migrations:** Alembic (22 migration files)

---

## 1. Table: `users`

Stores user accounts with local email/password authentication.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | Internal user ID (used in JWT sub claim) |
| full_name | VARCHAR(100) | NOT NULL | | User's display name |
| email | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | | Login email |
| hashed_password | VARCHAR(255) | NULLABLE | | bcrypt hash; NULL for legacy Clerk users |
| email_verified | BOOLEAN | NOT NULL | false | True after OTP verification |
| is_active | BOOLEAN | NOT NULL | true | Soft delete / deactivation |
| credits | INTEGER | NOT NULL | 50 | Deducted by AI calls (5 per call) |
| clerk_user_id | VARCHAR(255) | UNIQUE, NULLABLE, INDEX | | Legacy Clerk migration field |
| auth_provider | VARCHAR(20) | NOT NULL | 'local' | 'local' or 'clerk' |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| updated_at | TIMESTAMPTZ | ON UPDATE now() | | |

**Indexes:** id (PK), email (unique), clerk_user_id (unique)

---

## 2. Table: `user_locations`

Active and historical location records per user.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| user_id | INTEGER | FK → users(id) ON DELETE CASCADE, INDEX | | |
| latitude | FLOAT | NOT NULL | | GPS coordinate |
| longitude | FLOAT | NOT NULL | | GPS coordinate |
| accuracy | FLOAT | NULLABLE | | Meters |
| altitude | FLOAT | NULLABLE | | Meters above sea level |
| speed | FLOAT | NULLABLE | | Meters/second |
| source | VARCHAR(10) | NOT NULL | 'gps' | 'gps' or 'manual' |
| is_current | BOOLEAN | NOT NULL, INDEX | true | Only one True per user |
| is_active | BOOLEAN | NOT NULL | true | Soft delete |
| client_timestamp | TIMESTAMPTZ | NULLABLE | | Client-provided time |
| metadata_notes | TEXT | NULLABLE | | Device info, notes |
| created_at | TIMESTAMPTZ | | now() | |
| updated_at | TIMESTAMPTZ | ON UPDATE now() | | |

**Unique Constraint:** Single `is_current=True` per user (`uix_user_locations_single_current`)

---

## 3. Table: `location_history`

Immutable audit trail of all location updates.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| user_id | INTEGER | FK → users(id) ON DELETE CASCADE, INDEX | | |
| location_id | INTEGER | FK → user_locations(id) ON DELETE SET NULL | | Reference to source location |
| latitude | FLOAT | NOT NULL | | |
| longitude | FLOAT | NOT NULL | | |
| accuracy | FLOAT | NULLABLE | | |
| altitude | FLOAT | NULLABLE | | |
| speed | FLOAT | NULLABLE | | |
| source | VARCHAR(10) | NOT NULL | | |
| created_at | TIMESTAMPTZ | INDEX | now() | |

---

## 4. Table: `search_queries`

Audit log of all user searches.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| user_id | INTEGER | NOT NULL, INDEX | | |
| search_mode | VARCHAR(10) | NOT NULL | | 'text' or 'nearby' |
| resolved_mode | VARCHAR(10) | NULLABLE | | |
| raw_query | TEXT | NULLABLE | | NULL for nearby-only calls |
| latitude | FLOAT | NULLABLE | | Bias location |
| longitude | FLOAT | NULLABLE | | |
| radius | FLOAT | NULLABLE | | |
| result_count | INTEGER | | 0 | |
| from_cache | BOOLEAN | NOT NULL | false | |
| created_at | TIMESTAMPTZ | INDEX | now() | |

**Indexes:** `ix_search_queries_user_created` on (user_id, created_at)

---

## 5. Table: `search_results`

Individual place results per search query.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| query_id | INTEGER | FK → search_queries(id) ON DELETE CASCADE, INDEX | | |
| user_id | INTEGER | NOT NULL, INDEX | | |
| place_id | VARCHAR(255) | NOT NULL, INDEX | | Google Place ID |
| display_name | VARCHAR(500) | NULLABLE | | |
| formatted_address | TEXT | NULLABLE | | |
| primary_type | VARCHAR(100) | NULLABLE | | |
| latitude | FLOAT | NULLABLE | | |
| longitude | FLOAT | NULLABLE | | |
| rating | FLOAT | NULLABLE | | |
| user_rating_count | INTEGER | NULLABLE | | |
| business_status | VARCHAR(50) | NULLABLE | | |
| rank_position | INTEGER | NOT NULL | 0 | Order in results |
| created_at | TIMESTAMPTZ | | now() | |

---

## 6. Table: `place_details`

Cached place data from Google Places API.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| place_id | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | | Google Place ID |
| display_name | VARCHAR(500) | NULLABLE | | |
| formatted_address | TEXT | NULLABLE | | |
| latitude | FLOAT | NULLABLE | | |
| longitude | FLOAT | NULLABLE | | |
| primary_type | VARCHAR(100) | NULLABLE | | |
| types | JSONB | NULLABLE | | Array of type strings |
| international_phone_number | VARCHAR(50) | NULLABLE | | |
| national_phone_number | VARCHAR(50) | NULLABLE | | |
| website_uri | TEXT | NULLABLE | | |
| google_maps_uri | TEXT | NULLABLE | | |
| rating | FLOAT | NULLABLE | | 1.0–5.0 |
| user_rating_count | INTEGER | NULLABLE | | |
| business_status | VARCHAR(50) | NULLABLE | | 'OPERATIONAL', etc. |
| opening_hours | JSONB | NULLABLE | | Periods + weekday descriptions |
| open_now | BOOLEAN | NULLABLE | | Snapshot at fetch time |
| photos | JSONB | NULLABLE | | Array of photo references |
| reviews | JSONB | NULLABLE | | Up to 5 reviews |
| price_level | VARCHAR(30) | NULLABLE | | PRICE_LEVEL_MODERATE, etc. |
| wheelchair_accessible_entrance | BOOLEAN | NULLABLE | | |
| editorial_summary | TEXT | NULLABLE | | |
| last_fetched_at | TIMESTAMPTZ | NOT NULL | now() | |
| knowledge_synced | BOOLEAN | NOT NULL | false | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| updated_at | TIMESTAMPTZ | ON UPDATE now() | | |

---

## 7. Table: `place_knowledge_sync`

Tracks Pinecone sync state per place.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| place_id | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | | |
| sync_status | VARCHAR(10) | NOT NULL, INDEX | 'pending' | pending/synced/failed |
| vector_count | INTEGER | | 0 | |
| pinecone_namespace | VARCHAR(300) | NULLABLE | | |
| source_version | VARCHAR(64) | NULLABLE | SHA-256 hash for change detection |
| error_message | TEXT | NULLABLE | | |
| synced_at | TIMESTAMPTZ | NULLABLE | | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| updated_at | TIMESTAMPTZ | ON UPDATE now() | | |

---

## 8. Table: `place_questions`

Audit log of individual questions asked about places.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| user_id | INTEGER | NOT NULL, INDEX | | |
| place_id | VARCHAR(255) | NOT NULL, INDEX | | |
| question_text | TEXT | NOT NULL | | |
| session_id | VARCHAR(36) | FK → place_qa_sessions(id) ON DELETE SET NULL, INDEX | | UUID |
| knowledge_available | BOOLEAN | NOT NULL | false | |
| pinecone_matches | INTEGER | | 0 | |
| created_at | TIMESTAMPTZ | NOT NULL, INDEX | now() | |

---

## 9. Table: `place_answer_logs`

Audit log of AI-generated answers.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| question_id | INTEGER | FK → place_questions(id) ON DELETE CASCADE, INDEX | | |
| session_id | VARCHAR(36) | FK → place_qa_sessions(id) ON DELETE SET NULL, INDEX | | UUID |
| user_id | INTEGER | NOT NULL, INDEX | | |
| place_id | VARCHAR(255) | NOT NULL, INDEX | | |
| answer_text | TEXT | NOT NULL | | |
| confidence_score | FLOAT | NULLABLE | | Average similarity |
| answer_source | VARCHAR(20) | NOT NULL | 'rag' | rag/structured_only/fallback |
| grounding_chunks | JSONB | NULLABLE | | Source text fragments |
| context_tokens | INTEGER | NULLABLE | | |
| model_used | VARCHAR(100) | NULLABLE | | |
| latency_ms | INTEGER | NULLABLE | | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |

---

## 10. Table: `place_qa_sessions`

Conversation sessions for place Q&A.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | VARCHAR(36) | PRIMARY KEY, INDEX | UUID4 | |
| user_id | INTEGER | NOT NULL, INDEX | | |
| place_id | VARCHAR(255) | NULLABLE, INDEX | | NULL for general chat |
| title | VARCHAR(255) | NOT NULL | 'New Q&A' | Auto-generated |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| updated_at | TIMESTAMPTZ | NOT NULL | now() | |
| last_message_at | TIMESTAMPTZ | NULLABLE, INDEX | | |
| is_deleted | BOOLEAN | NOT NULL | false | Soft delete |

**Relationships:** Has many `place_qa_messages` via `session_id`

---

## 11. Table: `place_qa_messages`

Individual messages within Q&A sessions.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| session_id | VARCHAR(36) | FK → place_qa_sessions(id) ON DELETE CASCADE, NOT NULL, INDEX | | |
| role | VARCHAR(20) | NOT NULL | | 'user' or 'assistant' |
| content | TEXT | NOT NULL | | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| token_count | INTEGER | NULLABLE | | tiktoken estimate |
| metadata_json | JSONB | NULLABLE | | answer_source, confidence |

---

## 12. Table: `ai_chat_sessions`

General AI chat sessions.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | VARCHAR(36) | PRIMARY KEY, INDEX | UUID4 | |
| user_id | INTEGER | NOT NULL, INDEX | | |
| title | VARCHAR(255) | NOT NULL | 'New Chat' | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| updated_at | TIMESTAMPTZ | NOT NULL | now() | |
| last_message_at | TIMESTAMPTZ | NULLABLE, INDEX | | |
| is_archived | BOOLEAN | NOT NULL | false | |

---

## 13. Table: `ai_chat_messages`

Individual messages within AI chat sessions.

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| id | SERIAL | PRIMARY KEY | | |
| session_id | VARCHAR(36) | FK → ai_chat_sessions(id) ON DELETE CASCADE, NOT NULL, INDEX | | |
| role | VARCHAR(20) | NOT NULL | | 'user' or 'assistant' |
| content | TEXT | NOT NULL | | |
| created_at | TIMESTAMPTZ | NOT NULL | now() | |
| token_count | INTEGER | NULLABLE | | |
| model_used | VARCHAR(100) | NULLABLE | | |

---

## Entity Relationships Diagram (Text)

```
users 1──N user_locations
users 1──N location_history
users 1──N search_queries 1──N search_results
users 1──N place_qa_sessions 1──N place_qa_messages
users 1──N ai_chat_sessions 1──N ai_chat_messages
users 1──N place_questions
users 1──N place_answer_logs
place_details 1──1 place_knowledge_sync
place_qa_sessions 1──N place_questions (optional FK)
place_qa_sessions 1──N place_answer_logs (optional FK)
place_questions 1──1 place_answer_logs
```

---

## Migration History (22 files)

| # | Migration | Purpose |
|---|-----------|---------|
| 1 | `5c82d1dc0a22` | Initial tables (users, locations, history) |
| 2 | `9b038a4ff5e5` | Phase 1: Search queries + search results |
| 3 | `bb7a81bae21d` | Phase 2: Place details |
| 4 | `816b502eadfd` | Phase 3: Place knowledge sync |
| 5 | `cb3b8c851c9d` | Phase 4: Place questions + answer logs |
| 6 | `e5f6a7b8c9d0` | Phase 5: Route logs |
| 7 | `a633cd1c3123` | Add chat conversations + messages |
| 8 | `add_credits_to_users` | Add credits column to users |
| 9 | `20260616161353` | Add place_id to conversations |
| 10 | `a283a1d31c28` | Create AI chat system, remove old |
| 11 | `20260616181215` | Refactor place QA to session-based |
| 12 | `1cfd5b0be024` | Place QA sessions (empty — logic in prev) |
| 13 | `20260617120000` | AI chat generic tables |
| 14 | `20260618190000` | Merge AI chat and credits heads |
| 15 | `a9f3b1c2d4e5` | Session ID integer → varchar(24) |
| 16 | `20260619000000` | UUID session IDs + fix user_id type |
| 17 | `20260619120000` | Local auth password not null prep |
| 18 | `20260620000000` | Clerk only cleanup |
| 19 | `0fa91a232bae` | Add Clerk auth columns |
| 20 | `f1a2b3c4d5e6` | Unique current location per user |
| 21 | `a1b2c3d4e5f6` | B21/B29 from_cache boolean + is_active not null |
| 22 | `5c82d1dc0a22` (update) | Initial tables updates |
