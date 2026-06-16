// ============================================
// Modern GeoMap Configuration
// ============================================

const CONFIG = {
    // API Configuration
    API_BASE_URL: 'http://localhost:8000/api/v1',
    
    // Storage Keys
    STORAGE_KEYS: {
        TOKEN: 'geomap_token',
        USER: 'geomap_user',
        LOCATION: 'geomap_location'
    },
    
    // Default Values
    DEFAULTS: {
        SEARCH_RADIUS: 5000,        // meters
        MAX_RESULTS: 10,            // places
        PHOTO_MAX_WIDTH: 800,       // pixels
        PHOTO_MAX_HEIGHT: 600       // pixels
    },
    
    // Animation Durations (ms)
    ANIMATIONS: {
        TOAST_DURATION: 3000,
        LOADING_MIN: 500,
        TRANSITION: 300
    }
};

// Utility Functions
const Utils = {
    // Show toast notification
    showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = `toast show ${type}`;
        
        setTimeout(() => {
            toast.classList.remove('show');
        }, CONFIG.ANIMATIONS.TOAST_DURATION);
    },
    
    // Show loading screen
    showLoading() {
        const loading = document.getElementById('loadingScreen');
        if (loading) {
            loading.style.display = 'flex';
            loading.classList.remove('fade-out');
        }
    },
    
    // Hide loading screen
    hideLoading() {
        const loading = document.getElementById('loadingScreen');
        if (loading) {
            setTimeout(() => {
                loading.classList.add('fade-out');
                setTimeout(() => {
                    loading.style.display = 'none';
                }, CONFIG.ANIMATIONS.TRANSITION);
            }, CONFIG.ANIMATIONS.LOADING_MIN);
        }
    },
    
    // Format distance
    formatDistance(meters) {
        if (meters < 1000) {
            return `${Math.round(meters)}m`;
        }
        return `${(meters / 1000).toFixed(1)}km`;
    },
    
    // Format rating
    formatRating(rating) {
        return rating ? `⭐ ${rating.toFixed(1)}` : 'N/A';
    },
    
    // Get stored token
    getToken() {
        return localStorage.getItem(CONFIG.STORAGE_KEYS.TOKEN);
    },
    
    // Set token
    setToken(token) {
        localStorage.setItem(CONFIG.STORAGE_KEYS.TOKEN, token);
    },
    
    // Remove token
    removeToken() {
        localStorage.removeItem(CONFIG.STORAGE_KEYS.TOKEN);
    },
    
    // Get stored user
    getUser() {
        const user = localStorage.getItem(CONFIG.STORAGE_KEYS.USER);
        return user ? JSON.parse(user) : null;
    },
    
    // Set user
    setUser(user) {
        localStorage.setItem(CONFIG.STORAGE_KEYS.USER, JSON.stringify(user));
    },
    
    // Remove user
    removeUser() {
        localStorage.removeItem(CONFIG.STORAGE_KEYS.USER);
    },
    
    // Get stored location
    getLocation() {
        const location = localStorage.getItem(CONFIG.STORAGE_KEYS.LOCATION);
        return location ? JSON.parse(location) : null;
    },
    
    // Set location
    setLocation(location) {
        localStorage.setItem(CONFIG.STORAGE_KEYS.LOCATION, JSON.stringify(location));
    },
    
    // Remove location
    removeLocation() {
        localStorage.removeItem(CONFIG.STORAGE_KEYS.LOCATION);
    },
    
    // Clear all storage
    clearStorage() {
        this.removeToken();
        this.removeUser();
        this.removeLocation();
    },
    
    // Format timestamp
    formatTime(date) {
        const now = new Date();
        const timestamp = new Date(date);
        const diff = now - timestamp;
        
        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        
        return timestamp.toLocaleDateString();
    },
    
    // Debounce function
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    // Check if authenticated
    isAuthenticated() {
        return !!this.getToken();
    },
    
    // Show/hide elements
    show(element) {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        if (element) {
            element.style.display = 'block';
        }
    },
    
    hide(element) {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        if (element) {
            element.style.display = 'none';
        }
    },
    
    // Toggle element visibility
    toggle(element) {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        if (element) {
            element.style.display = element.style.display === 'none' ? 'block' : 'none';
        }
    }
};
