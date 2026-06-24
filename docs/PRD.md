# 📋 Product Requirements Document (PRD)

## GeoMap — Location-Based Discovery Platform

**Version:** 3.0.0
**Date:** June 22, 2026

---

## 1. Product Overview

GeoMap is a location-based discovery platform that helps users explore nearby places, get AI-powered answers about locations, calculate optimized routes with real-time traffic, and plan trips. The platform provides both REST API and WebSocket streaming interfaces.

### Core Value Proposition
- **Discover** places near you using intelligent search
- **Navigate** with optimized routes and live traffic data
- **Learn** about places through AI-powered Q&A
- **Plan** trips with multi-stop routing and departure time optimization

---

## 2. Target Users

| User Type | Needs | Use Case |
|-----------|-------|----------|
| Travelers | Find attractions, restaurants, hotels | "Show me famous places near me" |
| Locals | Discover new spots, get directions | "Find cafes open now within 2km" |
| Commuters | Calculate ETAs, avoid traffic | "Route to office with traffic" |
| Trip Planners | Multi-stop itineraries | "Plan a day trip with 5 stops" |

---

## 3. User Stories

### Authentication
- As a user, I want to register with email and password
- As a user, I want to verify my email via OTP
- As a user, I want to login and get JWT tokens
- As a user, I want to refresh my tokens without re-login
- As a user, I want to logout and revoke my tokens

### Location
- As a user, I want to share my GPS location
- As a user, I want to manually set my location
- As a user, I want to view my location history
- As a user, I want to delete my current location

### Discovery
- As a user, I want to text-search for places (e.g. "best pizza near me")
- As a user, I want to browse nearby places by category
- As a user, I want to autocomplete place names as I type
- As a user, I want to filter by ratings, open status, and distance

### Place Details
- As a user, I want to see full details about a place
- As a user, I want to view photos, reviews, and opening hours
- As a user, I want to see price levels and accessibility info

### Routes
- As a user, I want to get directions from my location to a place
- As a user, I want to see real-time traffic delays
- As a user, I want to plan multi-stop routes
- As a user, I want to optimize waypoint order
- As a user, I want to set departure time for future trips
- As a user, I want to compare ETAs for multiple destinations

### AI Q&A (General Chat)
- As a user, I want to ask travel questions in natural language
- As a user, I want to continue previous conversations
- As a user, I want streaming responses via WebSocket

### Place Q&A
- As a user, I want to ask questions about a specific place
- As a user, I want to get answers grounded in the place's data
- As a user, I want to see source attribution for answers

### Weather
- As a user, I want to check the weather forecast at my location
- As a user, I want to check air quality data

---

## 4. Functional Requirements

### FR-1: User Authentication
- Email/password registration with OTP email verification
- JWT access tokens (1 hour) + refresh tokens (7 days)
- Token rotation on refresh (old token invalidated)
- Token blacklisting on logout

### FR-2: Location Management
- GPS location updates from mobile/web clients
- Manual location setting with coordinates
- Duplicate detection within 10m threshold
- Location history with pagination
- Soft delete (deactivate) current location

### FR-3: Place Discovery
- Google Text Search with natural language queries
- Google Nearby Search with type filters and presets
- Autocomplete with location bias
- Redis caching (1 hour TTL)
- Audit logging of all searches

### FR-4: Place Details
- Fetch from Google Places API (New)
- Three-tier cache: Redis → PostgreSQL → Google
- Stale data detection (7-day threshold)
- Concurrent request deduplication with Redis lock
- Auto-trigger knowledge sync on new data

### FR-5: Route Computation
- Single route with traffic awareness
- Route matrix for batch ETA comparisons
- Multi-stop routes (up to 25 waypoints)
- Waypoint order optimization
- Departure time planning
- Multiple travel modes: DRIVE, WALK, BICYCLE, TWO_WHEELER
- Route modifiers: avoid tolls, highways, ferries

### FR-6: AI Chat
- General travel assistant conversation
- Session-based conversation history
- Credit-based usage (5 credits per message)
- 100 sessions max per user
- Streaming via WebSocket

### FR-7: Place Q&A
- RAG (Retrieval-Augmented Generation) over place knowledge
- Structured facts + Pinecone vector search
- Source-grounded answers with confidence scores
- Session-based conversation history
- Audit logging of questions and answers

### FR-8: Weather
- 7-day forecast with hourly and daily data
- Air quality index (PM2.5, PM10)
- Uses user's saved location automatically

---

## 5. Non-Functional Requirements

### Performance
- API response time < 500ms for cached results
- WebSocket streaming latency < 200ms per token
- Redis cache hit rate target > 70%

### Reliability
- Graceful degradation when Redis is unavailable
- Circuit breaker for external API calls
- Automatic retry with exponential backoff
- Crash logging to dedicated file

### Security
- JWT with HS256 signing
- Refresh token rotation (single-use)
- Token blacklisting via Redis
- Bcrypt password hashing
- Rate limiting (SlowAPI) on all endpoints
- CORS configured for frontend domains

### Scalability
- Connection pooling for external APIs
- Thread pool executor for Pinecone operations
- Stateless API design (horizontal scaling ready)
- Database connection pool (10 + 20 overflow)

---

## 6. Constraints

- PostgreSQL as primary database
- Redis for caching and token management
- Google Places API (New) for places data
- OpenAI for embeddings and chat completions
- Pinecone as vector database for RAG
- No frontend framework (vanilla HTML/CSS/JS)

---

## 7. Future Scope

- Mobile push notifications
- Social features (share routes, reviews)
- Offline mode with local caching
- Multi-language support
- Premium subscription tiers
- Place photo uploads from users
- Public transit routing
