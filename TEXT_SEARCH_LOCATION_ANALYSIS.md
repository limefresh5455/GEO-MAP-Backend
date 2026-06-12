# Text Search Location Bias Analysis

## 🔍 Current Implementation

### How Text Search Uses Location Coordinates:

Your text search API currently **does NOT directly return location coordinates in search results**. Instead:

1. **Location is used as a BIAS (soft preference)** to Google Places API
2. **Coordinates returned are the user's saved location** (not the place coordinates)
3. **Response includes `search_latitude` and `search_longitude`** - these are the **CENTER POINT** of the search, NOT individual place locations

---

## 📊 Current Flow

```
User Query: "Coffee shops"
       ↓
Text Search API receives request
       ↓
Check: use_user_location_as_bias = true (default)
       ↓
Fetch User's Saved Location from DB
   → user_locations table WHERE is_current=true
       ↓
Location: (22.7196, 75.8577) ✅ FOUND
       ↓
Send to Google Places Text Search API:
   {
     "textQuery": "Coffee shops",
     "locationBias": {
       "circle": {
         "center": {"latitude": 22.7196, "longitude": 75.8577},
         "radius": 5000.0  // 5km default
       }
     }
   }
       ↓
Google returns places biased towards that location
       ↓
Response to user:
   {
     "data": [
       {
         "place_id": "ChI...",
         "display_name": "Starbucks",
         "latitude": 22.7205,    ← PLACE ka coordinate
         "longitude": 75.8590    ← PLACE ka coordinate
       }
     ],
     "search_latitude": 22.7196,   ← USER ka saved location (bias center)
     "search_longitude": 75.8577   ← USER ka saved location (bias center)
   }
```

---

## 🎯 Key Points

### 1. **Location Bias vs Location Restriction**

**Current (Location Bias):**
- ✅ Soft preference
- ✅ Results OUTSIDE the area CAN appear if highly relevant
- ✅ Google considers relevance + distance
- ✅ Better for queries like "best pizza" (might return famous place 10km away)

**Alternative (Location Restriction):**
- ⚠️ Hard boundary
- ⚠️ Results MUST be within the radius
- ⚠️ Only distance matters
- ⚠️ Used by `/nearby-search` endpoint (existing)

### 2. **User's Saved Location Source**

Code location: `app/services/discovery_service.py` (lines 154-168)

```python
def _get_user_location(self, user_id: int) -> Optional[UserLocation]:
    """Fetch the active current location for a user."""
    return (
        self.db.query(UserLocation)
        .filter(
            UserLocation.user_id == user_id,
            UserLocation.is_current.is_(True),  # ← Current active location
            UserLocation.is_active.is_(True),   # ← Not deleted
        )
        .first()
    )
```

**This fetches:**
- User's **most recent saved location**
- Could be from GPS (`POST /api/v1/locations/gps`)
- Or manual (`PUT /api/v1/locations/manual`)

---

## ⚖️ Should You Change This? Analysis

### Option 1: Keep Current Behavior (RECOMMENDED ✅)

**Pros:**
- ✅ **Better UX**: User can search broadly while still getting relevant nearby results
- ✅ **Flexible**: "Pizza near me" will use current location, but "Pizza in Mumbai" works too
- ✅ **Google's Best Practice**: Text Search is designed for location bias, not restriction
- ✅ **No code changes needed**
- ✅ **Works even if GPS is slightly off**

**Cons:**
- ⚠️ Results might include places far away if they're highly relevant/rated
- ⚠️ User might see places 10-15km away for broad queries

**Use Cases:**
- ✅ "Best restaurants" → Might include famous place 5km away
- ✅ "Coffee near me" → Strongly biased to nearby, but not hard-limited
- ✅ "Pizza in Indore" → Location name overrides GPS bias
- ✅ Works well when user's GPS is not perfectly accurate

---

### Option 2: Always Use Current Location as Hard Restriction (NOT RECOMMENDED ❌)

**What would change:**
```python
# Change locationBias to locationRestriction
payload["locationRestriction"] = {
    "circle": {
        "center": {"latitude": lat, "longitude": lon},
        "radius": 5000  # Hard limit
    }
}
```

**Pros:**
- ✅ Results ONLY within radius
- ✅ Very predictable

**Cons:**
- ❌ **Breaks semantic search**: "Taj Mahal" won't work if you're not in Agra
- ❌ **Loses highly relevant results**: Best-rated restaurant 6km away won't show
- ❌ **Duplicate functionality**: You already have `/nearby-search` for this
- ❌ **Google discourages this**: Text Search is meant for flexible queries

---

### Option 3: Make Location Bias OPTIONAL (MIDDLE GROUND ⚖️)

**What would change:**
- Keep current behavior as default
- Add option to disable location bias

```python
# Schema change in TextSearchRequest:
use_user_location_as_bias: bool = Field(
    default=True,  # ← Current behavior
    description="Set to False to search globally without location bias"
)
```

**Pros:**
- ✅ Flexibility: User can choose
- ✅ Backward compatible
- ✅ Good for "tourist" searches far from current location

**Cons:**
- ⚠️ More complexity in API
- ⚠️ Frontend needs to understand the toggle

---

## 🎬 Recommendation

### **KEEP CURRENT BEHAVIOR** ✅

**Why:**

1. **It's the correct implementation** according to Google's docs
2. **Your API already has 3 endpoints for different use cases:**
   - `/text-search` → Flexible, with soft location bias ✅ **Current**
   - `/nearby-search` → Hard geo-bounded search ✅ **Already exists**
   - `/search` (router) → Automatically picks based on query ✅ **Already exists**

3. **Users get best of both worlds:**
   - "Coffee near me" → Uses location bias, shows nearby
   - "Taj Mahal" → Location doesn't restrict, finds correct place
   - "Restaurants in Indore" → Place name overrides GPS

4. **Your logs show it working correctly:**
   ```
   Text Search — query: 'Find Near Coffee Shop'
   → bias: (22.7196, 75.8577) r=500.0
   → returned 1 result ✅
   ```

---

## 📝 Understanding Response Coordinates

### Response Structure:

```json
{
  "success": true,
  "search_mode": "text",
  "data": [
    {
      "place_id": "ChIJ...",
      "display_name": "Cafe Coffee Day",
      "latitude": 22.7205,         ← PLACE ka actual location
      "longitude": 75.8590,        ← PLACE ka actual location
      "rating": 4.2
    }
  ],
  "search_latitude": 22.7196,      ← USER ka saved location (bias center)
  "search_longitude": 75.8577,     ← USER ka saved location (bias center)
  "query": "Coffee shops"
}
```

**Two sets of coordinates:**

1. **`data[].latitude/longitude`** (per place)
   - **Purpose**: Show WHERE each place is located
   - **Use**: Display markers on map
   - **Source**: Google Places API response

2. **`search_latitude/longitude`** (global)
   - **Purpose**: Show WHERE the search was centered
   - **Use**: Center the map initially, show search radius
   - **Source**: User's saved location from your database

---

## 🔧 If You Want to Change It...

### Change 1: Remove Location Bias Entirely

```python
# In app/services/discovery_service.py, line ~275
# Change default to False:
use_user_location_as_bias: bool = Field(
    default=False,  # ← Changed from True
    description="Disable automatic location biasing"
)
```

**Impact:**
- Text search becomes purely semantic (no GPS bias)
- User must include location in query text ("coffee in Raipur")

---

### Change 2: Use Current Location as Hard Restriction

```python
# In app/integrations/google_text_search.py
# Change _build_payload method:

if location_bias_lat is not None and location_bias_lon is not None:
    radius = location_bias_radius or 5000.0
    # CHANGE: Use locationRestriction instead of locationBias
    payload["locationRestriction"] = {  # ← Changed from locationBias
        "circle": {
            "center": {
                "latitude": location_bias_lat,
                "longitude": location_bias_lon,
            },
            "radius": radius,
        }
    }
```

**Impact:**
- Results ONLY within radius
- Makes text-search identical to nearby-search (redundant)

---

### Change 3: Make Radius Configurable

```python
# In app/schemas/discovery.py, TextSearchRequest:

location_bias_radius: Optional[float] = Field(
    default=5000.0,  # Current hardcoded value
    ge=100.0,
    le=50000.0,
    description="Location bias radius in meters (100-50000)"
)
```

**Impact:**
- Users can control bias strength
- More flexibility

---

## 🧪 Test Current Behavior

### Test 1: Location-aware search

```bash
# Should return results near (22.7196, 75.8577)
curl -X POST "http://localhost:8000/api/v1/discovery/text-search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text_query": "restaurants",
    "use_user_location_as_bias": true
  }'
```

**Expected:**
- `search_latitude`: 22.7196 (user's location)
- `data[0].latitude`: ~22.72 (place near user)

---

### Test 2: Global search (no bias)

```bash
# Should find Taj Mahal even if you're in Indore
curl -X POST "http://localhost:8000/api/v1/discovery/text-search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text_query": "Taj Mahal",
    "use_user_location_as_bias": false
  }'
```

**Expected:**
- `search_latitude`: null (no bias)
- `data[0].latitude`: 27.1751 (Agra, not your city!)

---

### Test 3: Check what's saved for your user

```bash
# See current saved location
curl -X GET "http://localhost:8000/api/v1/locations/current" \
  -H "Authorization: Bearer $TOKEN"
```

**Expected:**
```json
{
  "latitude": 22.7196,
  "longitude": 75.8577,
  "source": "gps",
  "is_current": true
}
```

This is what text-search is using as bias!

---

## 📊 Summary Table

| Scenario | Current Behavior | If Changed to Restriction |
|----------|-----------------|---------------------------|
| "Coffee near me" | ✅ Nearby places (soft preference) | ✅ Only within radius |
| "Taj Mahal" | ✅ Finds Taj Mahal anywhere | ❌ Returns nothing (not in radius) |
| "Pizza in Mumbai" | ✅ Finds places in Mumbai | ❌ Only in user's radius |
| GPS slightly off | ✅ Still finds nearby places | ⚠️ Might miss places just outside |
| Broad query "restaurants" | ⚠️ Might include 10km away | ✅ Hard limited to radius |

---

## ✅ Final Recommendation

### **DON'T CHANGE IT** - Current implementation is correct!

**Reasons:**
1. ✅ Follows Google Places API best practices
2. ✅ Provides best user experience
3. ✅ You already have `/nearby-search` for hard geo-bounded searches
4. ✅ Works correctly as designed
5. ✅ Flexible for both "near me" and semantic queries

**Only change if:**
- Users are complaining about results too far away
- You want to add a configurable radius parameter
- You need pure GPS-based search without semantic understanding

---

## 🎯 Current Status: ✅ WORKING AS INTENDED

**Your text search API:**
- ✅ Uses user's saved location as soft bias
- ✅ Returns place coordinates for each result
- ✅ Returns search center coordinates (user's location)
- ✅ Allows both "near me" and semantic queries
- ✅ Follows Google's recommended patterns

**No changes needed!** 🎉

---

**Document created:** June 12, 2026  
**Status:** Analysis Complete  
**Recommendation:** KEEP CURRENT IMPLEMENTATION
