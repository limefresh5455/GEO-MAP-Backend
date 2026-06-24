# 🌐 GeoMap API — Usage Guide

**Base URL:** `http://localhost:8000/api/v1`
**WebSocket URL:** `ws://localhost:8000/ws/chat`
**OpenAPI Docs (Swagger):** `http://localhost:8000/docs`

---

## Authentication

All protected endpoints require the following header:

```
Authorization: Bearer <access_token>
```

To get tokens, call `POST /auth/signup` → `POST /auth/verify-otp` (or `POST /auth/login` if already registered).

---

# 1. Authentication Endpoints

## POST /auth/signup — Register & Send OTP

**Auth:** None  
**Rate limit:** 5/minute  
**Use case:** Create a new account. Sends a 6-digit OTP to the email for verification.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "password": "MyPassword1"
  }'
```

**Example Response (200):**
```json
{
  "message": "Verification code sent. Check your email and call POST /auth/verify-otp.",
  "email": "jane@example.com",
  "otp_expires_in_seconds": 120
}
```

**Error Response (409 — Duplicate email):**
```json
{
  "detail": "An account with this email already exists. Please log in."
}
```

---

## POST /auth/verify-otp — Verify OTP & Create Account

**Auth:** None  
**Rate limit:** 10/minute  
**Use case:** Submit the OTP received via email. On success, creates the account and returns JWT tokens.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jane@example.com",
    "otp": "482910"
  }'
```

**Example Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_expires_in": 604800,
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "is_active": true,
    "email_verified": true,
    "credits": 50,
    "created_at": "2026-06-23T10:00:00Z",
    "updated_at": "2026-06-23T10:00:00Z"
  }
}
```

**Error Response (400 — Invalid/expired OTP):**
```json
{
  "detail": "Invalid or expired verification code. Check the code or call POST /auth/signup again to get a new one."
}
```

---

## POST /auth/login — Login

**Auth:** None  
**Rate limit:** 10/minute  
**Use case:** Authenticate with email and password. Returns JWT token pair.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jane@example.com",
    "password": "MyPassword1"
  }'
```

**Example Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_expires_in": 604800,
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "is_active": true,
    "email_verified": true,
    "credits": 50,
    "created_at": "2026-06-23T10:00:00Z",
    "updated_at": "2026-06-23T10:00:00Z"
  }
}
```

**Error Response (401 — Invalid credentials):**
```json
{
  "detail": "Invalid email or password."
}
```

---

## POST /auth/refresh — Refresh Tokens

**Auth:** None (uses refresh token from body)  
**Rate limit:** 20/minute  
**Use case:** Exchange a valid refresh token for a brand-new access + refresh token pair. Old refresh token is blacklisted (rotation).

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
  }'
```

**Example Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_expires_in": 604800,
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "is_active": true,
    "email_verified": true,
    "credits": 50,
    "created_at": "2026-06-23T10:00:00Z",
    "updated_at": "2026-06-23T10:00:00Z"
  }
}
```

**Error Response (401 — Blacklisted or invalid token):**
```json
{
  "detail": "Refresh token has been revoked. Please log in again."
}
```

---

## POST /auth/logout — Logout

**Auth:** Bearer token required  
**Rate limit:** 10/minute  
**Use case:** Blacklist the current access token and optionally the refresh token. After logout, neither token works.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
  }'
```

**Example Response (200):**
```json
{
  "message": "Logged out successfully. Tokens revoked."
}
```

---

## GET /auth/me — Current User Profile

**Auth:** Bearer token required  
**Use case:** Get the currently authenticated user's profile.

**Example Request:**
```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "id": 1,
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "is_active": true,
  "email_verified": true,
  "credits": 50,
  "created_at": "2026-06-23T10:00:00Z",
  "updated_at": "2026-06-23T10:00:00Z"
}
```

---

# 2. Location Endpoints

## POST /locations/gps — Update GPS Location

**Auth:** Bearer token required  
**Use case:** Update the user's current location from GPS data. Duplicate detection within ~10m prevents unnecessary writes.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/locations/gps \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "latitude": 28.6304,
    "longitude": 77.2177,
    "accuracy": 10.0,
    "altitude": 200.0,
    "speed": 1.5,
    "client_timestamp": "2026-06-23T10:30:00Z"
  }'
```

**Example Response (200 — New location saved):**
```json
{
  "success": true,
  "is_new": true,
  "message": "GPS location saved",
  "data": {
    "id": 42,
    "latitude": 28.6304,
    "longitude": 77.2177,
    "accuracy": 10.0,
    "altitude": 200.0,
    "source": "gps",
    "is_current": true,
    "created_at": "2026-06-23T10:30:00Z"
  }
}
```

---

## PUT /locations/manual — Set Manual Location

**Auth:** Bearer token required  
**Use case:** Manually set the user's location (e.g., from a map click or address search).

**Example Request:**
```bash
curl -X PUT http://localhost:8000/api/v1/locations/manual \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "latitude": 28.6304,
    "longitude": 77.2177,
    "metadata_notes": "Selected from map"
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "message": "Manual location saved",
  "data": {
    "id": 43,
    "latitude": 28.6304,
    "longitude": 77.2177,
    "source": "manual",
    "is_current": true,
    "metadata_notes": "Selected from map",
    "created_at": "2026-06-23T10:35:00Z"
  }
}
```

---

## GET /locations/me — Get Current Location

**Auth:** Bearer token required  
**Use case:** Get the user's current active location.

**Example Request:**
```bash
curl -X GET http://localhost:8000/api/v1/locations/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "latitude": 28.6304,
  "longitude": 77.2177,
  "accuracy": 10.0,
  "altitude": 200.0,
  "speed": 0,
  "source": "gps",
  "is_current": true,
  "is_active": true,
  "metadata_notes": null,
  "created_at": "2026-06-23T10:30:00Z"
}
```

**Error Response (404 — No location):**
```json
{
  "detail": "User has no saved location. Set a location first via POST/PUT."
}
```

---

## GET /locations/history — Get Location History

**Auth:** Bearer token required  
**Use case:** Get paginated location history.

**Query params:** `page=1` (default), `page_size=20` (default, max 100)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/locations/history?page=1&page_size=10" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "items": [
    {
      "id": 42,
      "latitude": 28.6304,
      "longitude": 77.2177,
      "accuracy": 10.0,
      "source": "gps",
      "created_at": "2026-06-23T10:30:00Z"
    },
    {
      "id": 41,
      "latitude": 28.6305,
      "longitude": 77.2178,
      "accuracy": 12.0,
      "source": "gps",
      "created_at": "2026-06-23T10:25:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 10,
  "has_next": true
}
```

---

## GET /locations/latest — Get Latest Location

**Auth:** Bearer token required  
**Use case:** Get the single most recent location record (may not be current if soft-deleted).

**Example Request:**
```bash
curl -X GET http://localhost:8000/api/v1/locations/latest \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "id": 42,
  "latitude": 28.6304,
  "longitude": 77.2177,
  "source": "gps",
  "is_current": true,
  "created_at": "2026-06-23T10:30:00Z"
}
```

---

## DELETE /locations/current — Deactivate Current Location

**Auth:** Bearer token required  
**Use case:** Soft-delete (deactivate) the current active location.

**Example Request:**
```bash
curl -X DELETE http://localhost:8000/api/v1/locations/current \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "message": "Current location deactivated"
}
```

---

# 3. Discovery Endpoints

## POST /discovery/search — Text Search

**Auth:** Bearer token required  
**Use case:** Search for places using natural language queries. Supports location bias (uses user's saved location or explicit bias).

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/discovery/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "text_query": "best coffee shops near me",
    "max_result_count": 10,
    "open_now": true,
    "min_rating": 4.0,
    "rank_preference": "RELEVANCE"
  }'
```

**Example Response (200):**
```json
{
  "places": [
    {
      "place_id": "ChIJh_UvczX9DDkRGz74wyQ-eSLM",
      "display_name": "Blue Tokai Coffee Roasters",
      "formatted_address": "29A, Khan Market, New Delhi, Delhi 110003",
      "primary_type": "cafe",
      "types": ["cafe", "restaurant", "point_of_interest"],
      "latitude": 28.6002,
      "longitude": 77.2272,
      "rating": 4.5,
      "user_rating_count": 1200,
      "business_status": "OPERATIONAL",
      "price_level": "PRICE_LEVEL_MODERATE",
      "photos": [
        {
          "name": "places/ChIJh_UvczX9DDkRGz74wyQ-eSLM/photos/AUc7tXnQ6mTpXQ",
          "width_px": 1600,
          "height_px": 900
        }
      ]
    }
  ],
  "from_cache": false,
  "latitude": 28.6304,
  "longitude": 77.2177
}
```

**Available Rank Preferences:** `RELEVANCE`, `DISTANCE`

---

## POST /discovery/nearby — Nearby Search

**Auth:** Bearer token required  
**Use case:** Discover places near the user's current location by category/preset.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/discovery/nearby \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "radius": 5000,
    "max_result_count": 15,
    "preset": "preferred_types",
    "rank_preference": "DISTANCE"
  }'
```

**Example Response (200):**
```json
{
  "places": [
    {
      "place_id": "ChIJh_UvczX9DDkRGz74wyQ-eSLM",
      "display_name": "Blue Tokai Coffee Roasters",
      "formatted_address": "29A, Khan Market, New Delhi, Delhi 110003",
      "primary_type": "cafe",
      "rating": 4.5,
      "distance_meters": 350,
      "business_status": "OPERATIONAL"
    }
  ],
  "from_cache": false,
  "latitude": 28.6304,
  "longitude": 77.2177
}
```

**Available Presets:** `preferred_types` (everyday places), `famous_places` (tourist attractions)
**Available Rank Preferences:** `POPULARITY`, `DISTANCE`

---

## GET /discovery/autocomplete — Autocomplete

**Auth:** Bearer token required  
**Use case:** Get place name suggestions as the user types. Location-biased.

**Query params:** `input` (required), `language_code` (default: `en`), `included_primary_types` (optional, comma-separated)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/discovery/autocomplete?input=Burj&language_code=en" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "predictions": [
    {
      "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
      "text": "Burj Khalifa",
      "main_text": "Burj Khalifa",
      "secondary_text": "Dubai, United Arab Emirates",
      "types": ["tourist_attraction", "point_of_interest", "establishment"]
    },
    {
      "place_id": "ChIJh_UvczX9DDkRz74wyQeSLM",
      "text": "Burj Al Arab",
      "main_text": "Burj Al Arab",
      "secondary_text": "Dubai, United Arab Emirates",
      "types": ["lodging", "point_of_interest", "establishment"]
    }
  ],
  "from_cache": false
}
```

---

# 4. Place Details Endpoint

## GET /places/{place_id}/details — Get Place Details

**Auth:** Bearer token required  
**Use case:** Get comprehensive details about a specific place. Uses 3-tier caching: Redis → PostgreSQL → Google Places API.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/places/ChIJh_UvczX9DDkRgztSPEWtB3w/details" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "success": true,
  "source": "google",
  "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
  "display_name": "Burj Khalifa",
  "formatted_address": "1 Sheikh Mohammed bin Rashid Blvd, Dubai, United Arab Emirates",
  "latitude": 25.1972,
  "longitude": 55.2744,
  "primary_type": "tourist_attraction",
  "types": ["tourist_attraction", "point_of_interest", "establishment"],
  "international_phone_number": "+971 4 888 8888",
  "national_phone_number": "04 888 8888",
  "website_uri": "https://www.burjkhalifa.ae/",
  "google_maps_uri": "https://maps.google.com/?cid=...",
  "rating": 4.6,
  "user_rating_count": 98765,
  "business_status": "OPERATIONAL",
  "price_level": "PRICE_LEVEL_EXPENSIVE",
  "open_now": true,
  "opening_hours": {
    "open_now": true,
    "weekday_descriptions": [
      "Monday: 10:00 AM – 10:00 PM",
      "Tuesday: 10:00 AM – 10:00 PM",
      "Wednesday: 10:00 AM – 10:00 PM",
      "Thursday: 10:00 AM – 11:00 PM",
      "Friday: 10:00 AM – 11:00 PM",
      "Saturday: 10:00 AM – 11:00 PM",
      "Sunday: 10:00 AM – 10:00 PM"
    ]
  },
  "photos": [
    {
      "name": "places/ChIJh_UvczX9DDkRgztSPEWtB3w/photos/AUc7tXnQ6mTpXQ",
      "width_px": 1600,
      "height_px": 900
    }
  ],
  "reviews": [
    {
      "author_name": "Traveler123",
      "rating": 5,
      "text": "Absolutely breathtaking view from the top!",
      "publish_time": "2026-05-15T08:30:00Z",
      "relative_publish_time_description": "a month ago"
    }
  ],
  "wheelchair_accessible_entrance": true,
  "editorial_summary": "The world's tallest building, standing at 828 meters..."
}
```

**Error Response (404 — Not found):**
```json
{
  "detail": "Place 'ChIJh_UvczX9DDkRgztSPEWtB3w' not found."
}
```

---

# 5. Place Q&A Endpoints

## POST /places/{place_id}/question — Ask a Question

**Auth:** Bearer token required  
**Rate limit:** 20/minute  
**Cost:** 5 credits  
**Use case:** Ask an AI-powered question about a specific place. Uses RAG (structured facts + Pinecone vectors). Creates or continues a session.

**Example Request (New session):**
```bash
curl -X POST http://localhost:8000/api/v1/places/ChIJh_UvczX9DDkRgztSPEWtB3w/question \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "question": "What are the opening hours and how much does it cost to visit?",
    "top_k": 5
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "answer": "The Burj Khalifa is open daily with varying hours. On weekdays (Monday–Wednesday), it's open from 10:00 AM to 10:00 PM, while Thursday through Saturday it stays open until 11:00 PM. Sunday hours are 10:00 AM to 10:00 PM.\n\nRegarding pricing, it's in the 'expensive' price range (PRICE_LEVEL_EXPENSIVE), which means premium/luxury pricing (₹₹₹₹). For specific ticket prices, I'd recommend checking their official website as rates vary by observation deck level and time of day.",
  "is_new_session": true,
  "title": "What are the opening hours...",
  "metadata": {
    "answer_source": "rag",
    "confidence_score": 0.85,
    "knowledge_synced": true,
    "pinecone_matches": 3,
    "model_used": "gpt-4o-mini",
    "context_tokens": 850,
    "grounding_fragments": [
      {
        "section": "structured_db",
        "text": "This is Burj Khalifa located at...",
        "similarity_score": 1.0,
        "source_type": "structured_db"
      },
      {
        "section": "hours",
        "text": "Opening hours: Monday: 10:00 AM – 10:00 PM...",
        "similarity_score": 0.92,
        "source_type": "pinecone"
      },
      {
        "section": "ratings",
        "text": "Price level: Expensive...",
        "similarity_score": 0.78,
        "source_type": "pinecone"
      }
    ]
  }
}
```

**Example Request (Continue session):**
```bash
curl -X POST http://localhost:8000/api/v1/places/ChIJh_UvczX9DDkRgztSPEWtB3w/question \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "question": "Is it wheelchair accessible?",
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "top_k": 5
  }'
```

---

## GET /places/qa/sessions — List Q&A Sessions

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Use case:** List all Q&A sessions for the current user, with optional filters.

**Query params:** `page=1`, `page_size=10`, `place_id=...` (optional filter), `search=...` (optional text search), `sort_by=last_message`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/places/qa/sessions?page=1&page_size=10" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "place": {
        "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
        "name": "Burj Khalifa",
        "address": "1 Sheikh Mohammed bin Rashid Blvd, Dubai"
      },
      "title": "What are the opening hours...",
      "last_message": "Yes, the Burj Khalifa is wheelchair accessible...",
      "message_count": 4,
      "last_message_at": "2026-06-23T11:00:00Z",
      "created_at": "2026-06-23T10:55:00Z"
    }
  ],
  "total": 1,
  "has_next": false
}
```

---

## GET /places/qa/sessions/{session_id} — Get Session Detail

**Auth:** Bearer token required  
**Use case:** Get a Q&A session with paginated messages.

**Query params:** `page=1`, `page_size=10`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/places/qa/sessions/a1b2c3d4-e5f6-7890-abcd-ef1234567890?page=1&page_size=10" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "session": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
    "title": "What are the opening hours...",
    "created_at": "2026-06-23T10:55:00Z",
    "last_message_at": "2026-06-23T11:00:00Z"
  },
  "messages": [
    {
      "role": "user",
      "content": "What are the opening hours and how much does it cost?",
      "created_at": "2026-06-23T10:55:00Z"
    },
    {
      "role": "assistant",
      "content": "The Burj Khalifa is open daily with varying hours...",
      "created_at": "2026-06-23T10:55:05Z",
      "metadata_json": {
        "answer_source": "rag",
        "confidence_score": 0.85,
        "pinecone_matches": 3
      }
    }
  ],
  "total": 2,
  "has_next": false
}
```

---

## PATCH /places/qa/sessions/{session_id} — Update Session Title

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Use case:** Rename a Q&A session.

**Example Request:**
```bash
curl -X PATCH http://localhost:8000/api/v1/places/qa/sessions/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "title": "Burj Khalifa Visit Planning"
  }'
```

**Example Response (200):**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "title": "Burj Khalifa Visit Planning",
  "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
  "created_at": "2026-06-23T10:55:00Z",
  "last_message_at": "2026-06-23T11:00:00Z"
}
```

---

## DELETE /places/qa/sessions — Delete Sessions

**Auth:** Bearer token required  
**Rate limit:** 20/minute  
**Use case:** Soft-delete one or more Q&A sessions.

**Query params:** `session_ids=a1b2c3d4, e5f6g7h8` (comma-separated IDs)

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/places/qa/sessions?session_ids=a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "deleted_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
  "message": "Sessions deleted successfully"
}
```

---

# 6. AI Chat (Travel Agent) Endpoints

## POST /chat/message — Send Chat Message

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Cost:** 5 credits  
**Use case:** Send a travel-related question to the AI travel assistant. Creates or continues a conversation session.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "query": "Plan a 2-day itinerary for exploring Dubai with family",
    "session_id": null
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "session_id": "x1y2z3a4-b5c6-7890-def0-1234567890ab",
  "reply": "Here's a 2-day family itinerary for Dubai:\n\n**Day 1: Iconic Landmarks**\n- Morning: Visit Burj Khalifa (At the Top observation deck)\n- Afternoon: Dubai Mall (aquarium, ice rink)\n- Evening: Dubai Fountain show\n\n**Day 2: Culture & Adventure**\n- Morning: Gold Souk & Spice Souk\n- Afternoon: Desert safari with dune bashing\n- Evening: Dinner at a traditional Arabian restaurant\n\nWould you like me to add restaurant recommendations or adjust the itinerary?",
  "is_new_session": true,
  "title": "Plan a 2-day itinerary...",
  "metadata": {
    "model_used": "gpt-4o-mini",
    "context_tokens": 450,
    "history_message_count": 0
  }
}
```

---

# 7. Routes Endpoints

## POST /routes/compute — Compute Route

**Auth:** Bearer token required  
**Use case:** Calculate a route with real-time traffic between the user's location and a destination. Supports multiple travel modes, waypoints, and route modifiers.

**Example Request (Single destination with traffic):**
```bash
curl -X POST http://localhost:8000/api/v1/routes/compute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
    "travel_mode": "DRIVE",
    "routing_preference": "TRAFFIC_AWARE",
    "waypoints": [],
    "optimize_waypoint_order": false,
    "avoid_tolls": false,
    "avoid_highways": false,
    "avoid_ferries": false
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "source": "google",
  "route": {
    "distance_meters": 12500,
    "duration_seconds": 900,
    "duration_in_traffic_seconds": 1200,
    "static_duration": "15 mins",
    "traffic_duration": "20 mins",
    "traffic_delay_seconds": 300,
    "traffic_delay": "5 mins",
    "has_traffic": true,
    "start_location": { "latitude": 28.6304, "longitude": 77.2177 },
    "end_location": { "latitude": 25.1972, "longitude": 55.2744 },
    "encoded_polyline": "io~uFz|shVk@e@kCsCkAm@",
    "travel_mode": "DRIVE",
    "steps": [
      {
        "instruction": "Head north on Sheikh Zayed Road",
        "distance_meters": 5000,
        "duration_seconds": 300,
        "polyline": "io~uFz|shVk@e@...",
        "travel_mode": "DRIVE",
        "start_location": { "latitude": 28.6304, "longitude": 77.2177 },
        "end_location": { "latitude": 28.6500, "longitude": 77.2200 }
      }
    ]
  }
}
```

**Available Travel Modes:** `DRIVE`, `WALK`, `BICYCLE`, `TWO_WHEELER`, `TRANSIT`
**Available Routing Preferences:** `TRAFFIC_AWARE`, `TRAFFIC_UNAWARE`

---

## POST /routes/matrix — Route Matrix

**Auth:** Bearer token required  
**Use case:** Compare ETAs for multiple destinations from the user's current location. Returns a matrix of distance and duration for each destination.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/routes/matrix \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "destinations": [
      { "lat": 25.1972, "lon": 55.2744, "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w", "display_name": "Burj Khalifa" },
      { "lat": 25.2048, "lon": 55.2708, "display_name": "Dubai Mall" }
    ],
    "travel_mode": "DRIVE",
    "routing_preference": "TRAFFIC_AWARE"
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "source": "google",
  "destination_count": 2,
  "travel_mode": "DRIVE",
  "destinations": [
    {
      "display_name": "Burj Khalifa",
      "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
      "distance_meters": 12500,
      "duration_seconds": 900,
      "duration": "15 mins",
      "traffic_delay_seconds": 300,
      "traffic_delay": "5 mins"
    },
    {
      "display_name": "Dubai Mall",
      "place_id": null,
      "distance_meters": 13000,
      "duration_seconds": 950,
      "duration": "16 mins",
      "traffic_delay_seconds": 180,
      "traffic_delay": "3 mins"
    }
  ]
}
```

---

# 8. Weather Endpoints

## POST /weather/forecast — Weather Forecast

**Auth:** Bearer token required  
**Rate limit:** 10/minute  
**Use case:** Get weather forecast for the user's saved location. Uses free Open-Meteo API.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/weather/forecast \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "start_date": "2026-06-23",
    "end_date": "2026-06-25"
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "message": "Weather forecast retrieved successfully",
  "data": {
    "location": {
      "latitude": 28.6304,
      "longitude": 77.2177,
      "elevation": 216.0,
      "timezone": "Asia/Kolkata",
      "utc_offset_seconds": 19800
    },
    "hourly": {
      "time": ["2026-06-23T00:00", "2026-06-23T01:00"],
      "temperature_2m": [28.5, 28.1],
      "relative_humidity_2m": [65, 68],
      "precipitation_probability": [10, 5],
      "weather_code": [1, 1]
    },
    "daily": {
      "time": ["2026-06-23", "2026-06-24", "2026-06-25"],
      "temperature_2m_max": [35.2, 36.0, 34.5],
      "temperature_2m_min": [26.8, 27.2, 26.5],
      "precipitation_sum": [0.0, 0.5, 0.0],
      "weather_code": [1, 3, 1]
    },
    "current_weather": {
      "temperature": 32.1,
      "weather_code": 1,
      "wind_speed": 5.2
    }
  }
}
```

---

## POST /weather/air-quality — Air Quality

**Auth:** Bearer token required  
**Rate limit:** 10/minute  
**Use case:** Get air quality data (PM2.5, PM10) for the user's saved location.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/weather/air-quality \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "start_date": "2026-06-23",
    "end_date": "2026-06-25"
  }'
```

**Example Response (200):**
```json
{
  "success": true,
  "message": "Air quality data retrieved successfully",
  "data": {
    "location": {
      "latitude": 28.6304,
      "longitude": 77.2177,
      "elevation": 216.0,
      "timezone": "Asia/Kolkata",
      "utc_offset_seconds": 19800
    },
    "hourly": {
      "time": ["2026-06-23T00:00", "2026-06-23T01:00"],
      "pm2_5": [45.2, 42.8],
      "pm10": [80.5, 75.3],
      "european_aqi": [3, 3]
    }
  }
}
```

---

# 9. Saved Places Endpoints

## POST /places/{place_id}/save — Save/Unsave a Place

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Use case:** Toggle save/unsave a place for quick access later.

**Example Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/places/ChIJh_UvczX9DDkRgztSPEWtB3w/save" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "note": "Want to visit next month"
  }'
```

**Example Response (200 — Saved):**
```json
{
  "success": true,
  "saved": true,
  "message": "Place saved successfully",
  "saved_place": {
    "id": 1,
    "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
    "note": "Want to visit next month",
    "created_at": "2026-06-23T12:00:00Z"
  }
}
```

**Example Response (200 — Unsaved if already saved):**
```json
{
  "success": true,
  "saved": false,
  "message": "Place unsaved"
}
```

---

## GET /places/saved — List Saved Places

**Auth:** Bearer token required  
**Use case:** Get all saved places for the current user.

**Query params:** `page=1`, `page_size=20`, `search=...` (optional filter)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/places/saved?page=1&page_size=20" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**Example Response (200):**
```json
{
  "items": [
    {
      "id": 1,
      "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
      "display_name": "Burj Khalifa",
      "formatted_address": "1 Sheikh Mohammed bin Rashid Blvd, Dubai",
      "rating": 4.6,
      "primary_type": "tourist_attraction",
      "note": "Want to visit next month",
      "saved_at": "2026-06-23T12:00:00Z"
    }
  ],
  "total": 1,
  "has_next": false
}
```

---

## PATCH /places/saved/{saved_id} — Update Saved Place

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Use case:** Update the note or label on a saved place.

**Example Request:**
```bash
curl -X PATCH "http://localhost:8000/api/v1/places/saved/1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "note": "Visit during the weekend"
  }'
```

---

## GET /places/saved/nearby — Nearby Saved Places

**Auth:** Bearer token required  
**Use case:** Get saved places near the user's current location.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/places/saved/nearby" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

# 10. Visit History Endpoints

## POST /places/{place_id}/visit — Log a Visit

**Auth:** Bearer token required  
**Rate limit:** 30/minute  
**Use case:** Log that the user visited a place.

**Example Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/places/ChIJh_UvczX9DDkRgztSPEWtB3w/visit" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "rating": 5,
    "notes": "Amazing view from the top!"
  }'
```

---

## GET /visits — List Visits

**Auth:** Bearer token required  
**Use case:** Get paginated visit history.

**Query params:** `page=1`, `page_size=20`

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/visits?page=1&page_size=20" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

## PATCH /visits/{visit_id} — Update Visit

**Auth:** Bearer token required  
**Use case:** Update notes or rating on a past visit.

---

## DELETE /visits/{visit_id} — Delete Visit

**Auth:** Bearer token required  
**Use case:** Remove a visit log.

---

## GET /visits/stats — Visit Statistics

**Auth:** Bearer token required  
**Use case:** Get aggregated visit statistics (total visits, unique places, etc.).

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/visits/stats" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

# 11. Comparison

## POST /comparison — Compare Places

**Auth:** Bearer token required  
**Use case:** Compare two or more places side by side.

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/comparison \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -d '{
    "place_ids": [
      "ChIJh_UvczX9DDkRgztSPEWtB3w",
      "ChIJh_UvczX9DDkRz74wyQ-eSLM"
    ]
  }'
```

---

# 12. WebSocket — Real-Time Streaming

**URL:** `ws://localhost:8000/ws/chat`

**Use case:** Real-time streaming for AI chat and place Q&A responses. Token-by-token delivery.

**Step 1 — Connect and authenticate:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat');
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'auth',
    token: 'Bearer eyJhbGciOiJIUzI1NiIs...'
  }));
};
```

**Step 2 — Receive connection confirmation:**
```json
{"type": "connected", "user_id": 1}
```

**Step 3a — Send a chat message:**
```json
{"type": "chat_message", "query": "Plan a 2-day trip to Dubai", "session_id": null}
```

**Step 3b — Or send a place question:**
```json
{
  "type": "place_question",
  "query": "Is this place open on Sunday?",
  "place_id": "ChIJh_UvczX9DDkRgztSPEWtB3w",
  "session_id": null
}
```

**Step 4 — Receive streaming response:**
```json
{"type": "metadata", "session_id": "uuid-here", "is_new_session": true}
{"type": "token", "content": "The Burj Khalifa "}
{"type": "token", "content": "is open on Sundays "}
{"type": "token", "content": "from 10:00 AM to 10:00 PM."}
{"type": "done", "title": "Burj Khalifa Hours", "metadata": {...}}
```

---

# Health Check

## GET / — Health Check

**Auth:** None  
**Use case:** Verify the server is running.

**Example Request:**
```bash
curl -X GET http://localhost:8000/
```

**Example Response (200):**
```json
{
  "status": "ok",
  "service": "geo-map-backend",
  "version": "3.0.0"
}
```

---

# Error Response Format

All errors follow this format:
```json
{
  "detail": "Human-readable error message"
}
```

**Common HTTP Status Codes:**

| Code | Meaning | When It Occurs |
|------|---------|----------------|
| 400 | Bad Request | Invalid input, validation error |
| 401 | Unauthorized | Missing/invalid/expired token |
| 402 | Payment Required | Insufficient credits for AI call |
| 403 | Forbidden | Inactive user, email not verified |
| 404 | Not Found | Place/session/resource not found |
| 409 | Conflict | Duplicate email, already saved |
| 422 | Validation Error | Request body fails schema validation |
| 429 | Rate Limit Exceeded | Too many requests per minute |
| 500 | Internal Server Error | Unexpected server error |
| 502 | Bad Gateway | External API error (Google, OpenAI) |
| 503 | Service Unavailable | Redis/Pinecone unavailable |
