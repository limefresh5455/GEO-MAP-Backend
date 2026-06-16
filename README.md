# 🗺️ GeoMap - Location-Based Discovery Platform

A complete location-based application with **FastAPI backend** and **responsive web frontend**. Search nearby places, calculate optimized routes with real-time traffic, and ask AI-powered questions about places.

## ✨ Features

### 🎯 Core Features
- **User Authentication** - Secure JWT-based auth
- **GPS Location Tracking** - Save and manage user locations
- **Place Discovery** - Search nearby restaurants, cafes, museums, etc.
- **Smart Routes** - Calculate routes with real-time traffic
- **AI Q&A** - Ask natural language questions about places

### 🚗 Advanced Routing (Phase 5, 6, 7)
- ✅ **Traffic Awareness** - Real-time delay estimates ("3 min delay")
- ✅ **Multi-Stop Routes** - Up to 25 waypoints with automatic optimization
- ✅ **Departure Time** - Plan future trips with traffic predictions
- ✅ **Travel Modes** - Drive, Walk, Bicycle
- ✅ **Route Options** - Avoid tolls, highways, ferries

### 🎨 Beautiful Frontend
- Clean, minimal design with bright, natural colors
- Fully responsive (mobile, tablet, desktop)
- No build step required (pure HTML/CSS/JS)
- Real-time toast notifications

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- PostgreSQL database
- Redis (optional, for caching)
- Google Maps API key
- OpenAI API key (for Q&A)
- Pinecone API key (for Q&A)

### 1. Clone & Setup

```bash
cd C:\Users\Administrator\Desktop\geo-map

# Install Python dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### 2. Database Setup

```bash
# Create database
createdb geomap

# Run migrations
alembic upgrade head
```

### 3. Start Backend (Terminal 1)

```bash
# Development mode
uvicorn app.main:app --reload --port 8000
```

Backend: `http://localhost:8000`
API Docs: `http://localhost:8000/docs`

### 4. Start Frontend (Terminal 2)

```bash
# Navigate to frontend
cd frontend

# Serve with Python
python -m http.server 3000
```

**OR** double-click: `start-frontend.bat`

Frontend: `http://localhost:3000`

### 5. Open Browser

Navigate to `http://localhost:3000` and start exploring!

## 📁 Project Structure

```
geo-map/
├── app/                       # Backend (FastAPI)
│   ├── api/v1/                # API endpoints
│   ├── core/                  # Config, security
│   ├── models/                # Database models
│   ├── services/              # Business logic
│   ├── integrations/          # Google, OpenAI APIs
│   └── schemas/               # Pydantic schemas
├── frontend/                  # Frontend (Vanilla JS)
│   ├── index.html             # Main app
│   ├── test.html              # API tester
│   ├── css/style.css          # Styles
│   └── js/                    # JavaScript modules
├── alembic/                   # Database migrations
├── .env                       # Environment config
├── requirements.txt           # Python dependencies
├── FRONTEND_GUIDE.md          # Complete setup guide
└── IMPLEMENTATION_SUMMARY.md  # What was built
```

## 🔧 Configuration

### Backend (.env)

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/geomap

# Google Maps
GOOGLE_PLACES_API_KEY=your_google_api_key
GOOGLE_ROUTES_BASE_URL=https://routes.googleapis.com/directions/v2

# OpenAI (for Q&A)
OPENAI_API_KEY=your_openai_key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Pinecone (for Q&A)
PINECONE_API_KEY=your_pinecone_key
PINECONE_ENVIRONMENT=us-east-1-aws
PINECONE_INDEX_NAME=place-knowledge

# Redis (optional)
REDIS_HOST=localhost
REDIS_PORT=6379

# JWT
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=10080
```

### Frontend (frontend/js/config.js)

```javascript
const CONFIG = {
    API_BASE_URL: 'http://localhost:8000/api/v1'
};
```

## 📖 Usage Guide

### Step 1: Register & Login
1. Open `http://localhost:3000`
2. Click **Register** → Fill form → Create account
3. **Login** with your credentials

### Step 2: Set Location
- **GPS:** Click "Use My GPS Location" button
- **Manual:** Enter latitude/longitude coordinates

### Step 3: Discover Places
1. Enter search query (e.g., "restaurants")
2. Set radius (default: 5000m)
3. Click **Search Places**

### Step 4: Get Directions
**Simple Route:**
- Click "Get Directions" on any place card
- View distance, duration, traffic delay

**Multi-Stop Route (Phase 6):**
- Click "+ Add Stop" to add waypoints
- Check "Optimize waypoint order"
- Calculate optimal route

**Future Trip (Phase 7):**
- Select departure time
- Get predicted traffic conditions

### Step 5: Ask Questions
- Click "Ask Question" on any place
- Type question: "What are the opening hours?"
- Get AI-powered answer

## 🐳 Docker Deployment

```bash
# Build and start all services
docker-compose up -d

# Run migrations
docker-compose exec api alembic upgrade head

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Create account |
| `/auth/login` | POST | User login |
| `/locations/gps` | POST | Set GPS location |
| `/discovery/search` | POST | Search nearby places |
| `/places/{id}` | GET | Place details |
| `/routes/compute` | POST | Calculate route |
| `/routes/matrix` | POST | Batch ETAs |
| `/place-qa/ask` | POST | Ask about place |

Full API docs: `http://localhost:8000/docs`

## 🧪 Testing

### Option 1: Manual Testing
1. Open frontend: `http://localhost:3000`
2. Register → Login → Search → Get Route

### Option 2: API Testing Page
1. Open: `http://localhost:3000/test.html`
2. Click test buttons in order
3. Verify all responses

### Option 3: Swagger UI
1. Open: `http://localhost:8000/docs`
2. Click "Authorize" → Enter token
3. Try endpoints

## 🎨 Design

The frontend uses a bright, natural color palette:

- 🌿 **Primary Green** (`#4CAF50`) - Fresh, natural
- 🧡 **Warm Orange** (`#FF9800`) - Friendly, inviting  
- 💙 **Sky Blue** (`#03A9F4`) - Trust, clarity
- 🌤️ **Sunny Yellow** (`#FFC107`) - Highlights
- 🌸 **Coral Red** (`#F44336`) - Alerts

Background: Soft gradient from light green to light blue

## 🐛 Troubleshooting

### CORS Errors
✅ Already configured! Backend allows:
- `http://localhost:3000` (Python server)
- `http://localhost:5500` (VS Code Live Server)

### Backend Not Starting
```bash
# Check PostgreSQL
sudo service postgresql status

# Check Redis (optional)
redis-cli ping

# Verify .env file
cat .env
```

### Frontend Not Loading
```bash
# Verify backend is running
curl http://localhost:8000/

# Check frontend config
cat frontend/js/config.js
```

### Location Not Working
- Enable browser location permissions
- Use HTTPS in production
- Try manual coordinates as fallback

## 📚 Documentation

- **[FRONTEND_GUIDE.md](./FRONTEND_GUIDE.md)** - Complete setup guide
- **[IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)** - What was built
- **[frontend/README.md](./frontend/README.md)** - Frontend-specific docs

## 🚀 Production Deployment

### Backend
1. Use production database URL
2. Set environment variables securely
3. Deploy with:
   ```bash
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

### Frontend
1. Update `API_BASE_URL` to production backend
2. Deploy to:
   - Vercel: `vercel --prod`
   - Netlify: Drag & drop `frontend` folder
   - GitHub Pages: Push to `gh-pages` branch

3. Update CORS in `app/main.py`:
   ```python
   allow_origins=["https://your-domain.com"]
   ```

## 📝 Technology Stack

**Backend:**
- FastAPI (Python web framework)
- PostgreSQL (Database)
- Redis (Caching)
- SQLAlchemy (ORM)
- Alembic (Migrations)
- Google Maps APIs
- OpenAI (Embeddings)
- Pinecone (Vector DB)

**Frontend:**
- Pure HTML5
- CSS3 (No preprocessors)
- Vanilla JavaScript (No frameworks)
- Modern ES6+ features

## 🤝 Contributing

This is a complete working project. To extend:

1. Backend: Add new endpoints in `app/api/v1/`
2. Frontend: Modify `frontend/js/app.js`
3. Database: Create migration with `alembic revision`

## 📄 License

This project demonstrates a complete location-based platform implementation.

## 🎉 Acknowledgments

- Google Maps Platform for Places & Routes APIs
- OpenAI for natural language processing
- Pinecone for vector search capabilities

---

**Ready to explore?** Open `http://localhost:3000` and start discovering! 🗺️
