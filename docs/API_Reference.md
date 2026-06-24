# 🌐 API Reference

## GeoMap — Location-Based Discovery Platform

**Base URL:** `http://localhost:8000/api/v1`
**WebSocket URL:** `ws://localhost:8000/api/v1/ws/chat`
**OpenAPI Docs:** `http://localhost:8000/docs`

---

## 1. Authentication

All protected endpoints require `Authorization: Bearer <access_token>` header.

### POST /auth/signup
Register a new account. Sends OTP to email.

```json
{
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "password": "Password1"
}
```
Response: `{ "message": "...", "email": "...", "otp_expires_in_seconds": 120 }`

### POST /auth/verify-otp
Verify OTP and create account.

```json
{
  "email": "jane@example.com",
  "otp": "482910"
}
```
Response: `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer", "user": {...} }`

### POST /auth/login
Login with email and password.

```json
{
  "email": "jane@example.com",
  "password": "Password1"
}
```
Response: Full token pair + user profile

### POST /auth/refresh
Exchange refresh token for new pair. Old refresh token is blacklisted.

```json
{
  "refresh_token": "..."
}
```
Response: New token pair + user profile

### POST /auth/logout
Blacklist current access + refresh token.

```json
{
  "refresh_token": "..."  // optional
}
```
Response: `{ "message": "Logged out successfully. Tokens revoked." }`

### GET /auth/me
Get current user profile.

Response: `{ "id": 1, "full_name": "...", "email": "...", "credits": 50, ... }`

---

## 2. Locations

### GET /locations/me
Get current active location.

### POST /locations/gps
Update location from GPS.

```json
{
  "latitude": 28.6304,
  "longitude": 77.2177,
  "accuracy": 10.0
}
```

### PUT /locations/manual
Manually set location.

```json
{
  "latitude": 28.6304,
  "longitude": 77.2177
}
```

### GET /locations/history
Paginated location history. Query params: `page=1`, `page_size=20`

### GET /locations/latest
Get most recent location record.

### DELETE /locations/current
Deactivate current location (soft delete).

---

## 3. Discovery

### POST /discovery/search
Text search for places.

```json
{
  "text_query": "best coffee near me",
  "max_result_count": 20,
  "open_now": true
}
```

### POST /discovery/nearby
Nearby discovery by category.

```json
{
  "radius": 5000,
  "preset": "preferred_types"
}
```

Available presets: `preferred_types`, `famous_places`

### GET /discovery/autocomplete
Place name autocomplete. Query params: `input=Burj`, `language_code=en`

---

## 4. Place Details

### GET /places/{place_id}/details
Full place details with 3-tier caching.

Response includes: display_name, formatted_address, rating, opening_hours, photos, reviews, price_level, accessibility, editorial_summary

---

## 5. Place Q&A

### POST /places/{place_id}/question
Ask an AI-powered question about a place.

```json
{
  "question": "What are the opening hours?",
  "session_id": null  // omit for new session
}
```

Response includes: answer, session_id, is_new_session, metadata (sources, confidence)

### GET /places/qa/sessions
List Q&A sessions. Query params: `page=1`, `page_size=10`, `place_id=...`, `search=...`

### GET /places/qa/sessions/{session_id}
Get session details with paginated messages.

### PATCH /places/qa/sessions/{session_id}
Update session title.

### DELETE /places/qa/sessions
Bulk delete sessions. Query param: `session_ids=id1,id2,id3`

---

## 6. AI Chat (Travel Agent)

### POST /chat/message
Send a travel-related question to the AI.

```json
{
  "query": "Plan a 2-day trip to Jaipur",
  "session_id": null
}
```

---

## 7. Routes

### POST /routes/compute
Calculate route with traffic.

```json
{
  "place_id": "ChIJ...",
  "travel_mode": "DRIVE",
  "waypoints": [{"lat": 28.6, "lon": 77.2}],
  "optimize_waypoint_order": false,
  "avoid_tolls": false
}
```

Travel modes: `DRIVE`, `WALK`, `BICYCLE`, `TWO_WHEELER`

Response includes: distance_meters, duration_seconds, traffic_delay_seconds, encoded_polyline, turn-by-turn steps

### POST /routes/matrix
Compare ETAs for multiple destinations.

```json
{
  "destinations": [
    {"lat": 28.6, "lon": 77.2, "place_id": "ChIJ..."},
    {"lat": 28.7, "lon": 77.3}
  ],
  "travel_mode": "DRIVE"
}
```

---

## 8. Weather

### POST /weather/forecast
Get weather forecast.

```json
{
  "start_date": "2026-06-22",
  "end_date": "2026-06-29"
}
```

### POST /weather/air-quality
Get air quality data.

```json
{
  "start_date": "2026-06-22",
  "end_date": "2026-06-29"
}
```

---

## 9. WebSocket

### ws://host/api/v1/ws/chat
Real-time streaming for AI chat and place Q&A.

**Authentication (first message):**
```json
{"type":"auth","token":"Bearer <access_token>"}
```

**Send chat message:**
```json
{"type":"chat_message","query":"Plan a trip","session_id":null}
```

**Send place question:**
```json
{
  "type":"place_question",
  "query":"Is it open on Sunday?",
  "place_id":"ChIJ...",
  "session_id":null,
  "top_k":5
}
```

**Receive stream:**
```json
{"type":"connected","user_id":123}
{"type":"metadata","session_id":"uuid","is_new_session":true}
{"type":"token","content":"The answer is..."}
{"type":"done","title":"New Chat"}
{"type":"error","message":"Something went wrong"}
```

---

## 10. Health

### GET /
Health check.

Response: `{ "status": "ok", "service": "geo-map-backend", "version": "3.0.0" }`

---

## Error Response Format

All errors return:
```json
{
  "detail": "Error message describing what went wrong"
}
```

Common HTTP status codes:
| Code | Meaning |
|------|---------|
| 400 | Bad request (validation) |
| 401 | Unauthorized (invalid/expired token) |
| 402 | Payment Required (insufficient credits) |
| 403 | Forbidden (inactive user) |
| 404 | Not found |
| 409 | Conflict (duplicate email) |
| 422 | Validation error |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 502 | Bad gateway (external API error) |
| 503 | Service unavailable (Redis/Pinecone down) |
| 504 | Gateway timeout |
