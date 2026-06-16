# 🗺️ GeoMap Frontend

Modern, clean, and animated frontend application for GeoMap.

## ⚠️ CRITICAL: Frontend Serving Requirements

### 🚫 DO NOT Open HTML Files Directly

**Opening `app.html` by double-clicking or using "Open with Browser" will cause CORS errors!**

This happens because the file uses `file://` protocol instead of `http://` protocol, and browsers block cross-origin requests from `file://` for security reasons.

**❌ WRONG (Will Cause CORS Errors):**
```
file:///C:/Users/Administrator/Desktop/geo-map/frontend/app.html
```

**✅ CORRECT (Required for API Access):**
```
http://localhost:3000/app.html
```

### ✅ Required: Use HTTP Development Server

You **MUST** use an HTTP server to serve the frontend. Choose one of these methods:

**Method 1 - Batch Script (Easiest):**
```bash
# From project root, double-click or run:
start-frontend.bat
```

**Method 2 - Python HTTP Server:**
```bash
cd frontend
python -m http.server 3000
```

**Method 3 - VS Code Live Server:**
1. Install "Live Server" extension in VS Code
2. Right-click `app.html` → "Open with Live Server"
3. Opens on `http://localhost:5500/app.html`

### 🌐 Then Open in Browser
```
http://localhost:3000/app.html
```

**Why This Matters:**
- Browser security requires same-origin policy compliance
- API calls from `file://` to `http://` are blocked by CORS
- HTTP server provides proper origin for cross-origin requests
- CORS headers from backend can only be evaluated with HTTP protocol

---

## 📁 Files

```
frontend/
├── app.html                      # Main application
├── test-modern.html             # Connection test page
├── css/
│   └── modern-style.css        # Styles
├── js/
│   ├── modern-config.js        # Configuration
│   ├── modern-api.js           # API layer
│   └── modern-app.js           # App logic
├── README.md                    # This file
├── MODERN-FRONTEND-README.md    # Full documentation
└── WORKFLOW-GUIDE.md            # Visual workflow
```

## 🚀 Quick Start

### 1. Start Backend
```bash
# From project root, run:
start-backend.bat

# Or manually:
uvicorn app.main:app --reload
```

### 2. Start Frontend HTTP Server

**⚠️ CRITICAL: Do NOT open app.html directly! CORS errors will occur!**

**Option A - Use Batch File (Easiest):**
```bash
# From project root, double-click or run:
start-frontend.bat
```

**Option B - Manual Python Server:**
```bash
cd frontend
python -m http.server 3000
```

**Option C - VS Code Live Server:**
```bash
# Install Live Server extension, then:
# Right-click app.html → "Open with Live Server"
```

### 3. Open Application in Browser
```
http://localhost:3000/app.html
```

**❌ WRONG (CORS Error):** `file:///C:/Users/.../app.html`  
**✅ CORRECT (Works):** `http://localhost:3000/app.html`

## 🎯 Features

✅ User Signup & Login  
✅ Location Confirmation (GPS or Manual)  
✅ Nearby Search & Text Query Search  
✅ Discover Places  
✅ Place Details with Photos (auto-loaded)  
✅ Knowledge Sync (auto-triggered)  
✅ Chat/Q&A Interface (multiple questions)  
✅ Clean, animated design  

## 🔧 Configuration

Edit `js/modern-config.js` to change API URL:

```javascript
const CONFIG = {
    API_BASE_URL: 'http://localhost:8000/api/v1',
    // ...
};
```

## 📖 Documentation

- **MODERN-FRONTEND-README.md** - Complete technical documentation
- **WORKFLOW-GUIDE.md** - Visual workflow with API calls
- **../FRONTEND-QUICK-START.md** - Quick setup guide
- **../NEW-FRONTEND-SUMMARY.md** - Complete summary

## 🎉 Ready to Use!

1. Start backend
2. Open `app.html`
3. Sign up → Login → Explore!

Enjoy your GeoMap application! 🗺️✨
