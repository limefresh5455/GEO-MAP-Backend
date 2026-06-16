// ============================================
// Modern GeoMap Application Logic
// ============================================

class GeoMapApp {
    constructor() {
        this.currentPlaceId = null;
        this.chatHistory = [];
        this.init();
    }
    
    // Initialize application
    init() {
        this.setupEventListeners();
        this.checkAuth();
    }
    
    // Setup all event listeners
    setupEventListeners() {
        // Auth tabs
        document.querySelectorAll('.auth-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchAuthTab(tab.dataset.tab));
        });
        
        // Auth forms
        document.getElementById('loginForm').addEventListener('submit', (e) => this.handleLogin(e));
        document.getElementById('signupForm').addEventListener('submit', (e) => this.handleSignup(e));
        
        // Location
        document.getElementById('useGPSBtn').addEventListener('click', () => this.useGPS());
        document.getElementById('manualLocationForm').addEventListener('submit', (e) => this.setManualLocation(e));
        
        // Navigation
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchSection(btn.dataset.section));
        });
        
        // User menu
        document.getElementById('userMenuBtn').addEventListener('click', () => this.toggleUserMenu());
        document.getElementById('logoutBtn').addEventListener('click', () => this.handleLogout());
        
        // Search options
        document.getElementById('nearbySearchBtn').addEventListener('click', () => this.openModal('nearbyModal'));
        document.getElementById('textSearchBtn').addEventListener('click', () => this.openModal('textModal'));
        
        // Search forms
        document.getElementById('nearbySearchForm').addEventListener('submit', (e) => this.handleNearbySearch(e));
        document.getElementById('textSearchForm').addEventListener('submit', (e) => this.handleTextSearch(e));
        
        // Discover
        document.getElementById('discoverPlacesBtn').addEventListener('click', () => this.handleDiscover());
        
        // Clear results
        document.getElementById('clearResults').addEventListener('click', () => this.clearResults());
        
        // Location update
        document.getElementById('updateLocationBtn').addEventListener('click', () => this.showLocationScreen());
        
        // Modal close buttons
        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => this.closeModal(btn.dataset.modal));
        });
        
        // Click outside modal to close
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal(modal.id);
                }
            });
        });
        
        // Range slider
        const radiusSlider = document.getElementById('nearbyRadius');
        if (radiusSlider) {
            radiusSlider.addEventListener('input', (e) => {
                document.getElementById('radiusValue').textContent = `${e.target.value}m`;
            });
        }
        
        // Chat form
        document.getElementById('chatForm').addEventListener('submit', (e) => this.handleChat(e));
    }
    
    // Check authentication status
    async checkAuth() {
        Utils.showLoading();
        
        if (Utils.isAuthenticated()) {
            try {
                const user = await API.auth.getMe();
                Utils.setUser(user);
                this.showApp(user);
            } catch (error) {
                console.error('Auth check failed:', error);
                Utils.clearStorage();
                this.showAuth();
            }
        } else {
            this.showAuth();
        }
        
        Utils.hideLoading();
    }
    
    // Show authentication screen
    showAuth() {
        Utils.hide('locationScreen');
        Utils.hide('appScreen');
        Utils.hide('navbar');
        Utils.show('authScreen');
    }
    
    // Show app
    async showApp(user) {
        Utils.hide('authScreen');
        Utils.show('navbar');
        
        // Update user name
        document.getElementById('userName').textContent = user.full_name || user.email.split('@')[0];
        
        // Check if location is set
        const location = Utils.getLocation();
        if (!location) {
            this.showLocationScreen();
        } else {
            this.showAppScreen();
            this.updateLocationDisplay();
        }
    }
    
    // Show location screen
    showLocationScreen() {
        Utils.hide('authScreen');
        Utils.hide('appScreen');
        Utils.hide('navbar');
        Utils.show('locationScreen');
    }
    
    // Show app screen
    showAppScreen() {
        Utils.hide('authScreen');
        Utils.hide('locationScreen');
        Utils.show('appScreen');
        Utils.show('navbar');
        this.switchSection('search');
    }
    
    // Switch auth tab
    switchAuthTab(tab) {
        document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
        
        if (tab === 'login') {
            Utils.show('loginForm');
            Utils.hide('signupForm');
        } else {
            Utils.hide('loginForm');
            Utils.show('signupForm');
        }
    }
    
    // Handle login
    async handleLogin(e) {
        e.preventDefault();
        
        const email = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;
        
        try {
            Utils.showLoading();
            const response = await API.auth.login(email, password);
            
            Utils.setToken(response.access_token);
            
            const user = await API.auth.getMe();
            Utils.setUser(user);
            
            Utils.showToast('Login successful!', 'success');
            this.showApp(user);
        } catch (error) {
            Utils.showToast(error.message || 'Login failed', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Handle signup
    async handleSignup(e) {
        e.preventDefault();
        
        const name = document.getElementById('signupName').value;
        const email = document.getElementById('signupEmail').value;
        const password = document.getElementById('signupPassword').value;
        
        try {
            Utils.showLoading();
            await API.auth.register(name, email, password);
            
            Utils.showToast('Account created! Please login.', 'success');
            this.switchAuthTab('login');
            
            // Pre-fill login email
            document.getElementById('loginEmail').value = email;
        } catch (error) {
            Utils.showToast(error.message || 'Signup failed', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Use GPS location
    async useGPS() {
        if (!navigator.geolocation) {
            Utils.showToast('Geolocation not supported', 'error');
            return;
        }
        
        Utils.showLoading();
        
        navigator.geolocation.getCurrentPosition(
            async (position) => {
                try {
                    const { latitude, longitude } = position.coords;
                    
                    await API.location.setGPS(latitude, longitude);
                    
                    Utils.setLocation({ latitude, longitude });
                    
                    Utils.show('locationStatus');
                    document.getElementById('locationCoords').textContent = 
                        `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
                    
                    Utils.showToast('Location set successfully!', 'success');
                    
                    setTimeout(() => {
                        this.showAppScreen();
                    }, 1500);
                } catch (error) {
                    Utils.showToast(error.message || 'Failed to set location', 'error');
                } finally {
                    Utils.hideLoading();
                }
            },
            (error) => {
                Utils.hideLoading();
                Utils.showToast('Failed to get GPS location', 'error');
            }
        );
    }
    
    // Set manual location
    async setManualLocation(e) {
        e.preventDefault();
        
        const latitude = parseFloat(document.getElementById('manualLat').value);
        const longitude = parseFloat(document.getElementById('manualLng').value);
        
        try {
            Utils.showLoading();
            
            await API.location.setGPS(latitude, longitude);
            
            Utils.setLocation({ latitude, longitude });
            
            Utils.show('locationStatus');
            document.getElementById('locationCoords').textContent = 
                `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
            
            Utils.showToast('Location set successfully!', 'success');
            
            setTimeout(() => {
                this.showAppScreen();
            }, 1500);
        } catch (error) {
            Utils.showToast(error.message || 'Failed to set location', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Update location display
    updateLocationDisplay() {
        const location = Utils.getLocation();
        if (location) {
            document.getElementById('currentLocationDisplay').textContent = 
                `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}`;
        }
    }
    
    // Switch section
    switchSection(section) {
        document.querySelectorAll('.app-section').forEach(s => s.classList.remove('active'));
        document.getElementById(`${section}Section`).classList.add('active');
        
        document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelector(`[data-section="${section}"]`).classList.add('active');
    }
    
    // Toggle user menu
    toggleUserMenu() {
        document.getElementById('userDropdown').classList.toggle('show');
    }
    
    // Handle logout
    handleLogout() {
        Utils.clearStorage();
        Utils.showToast('Logged out successfully', 'success');
        this.showAuth();
    }
    
    // Open modal
    openModal(modalId) {
        document.getElementById(modalId).classList.add('show');
    }
    
    // Close modal
    closeModal(modalId) {
        document.getElementById(modalId).classList.remove('show');
    }
    
    // Handle nearby search
    async handleNearbySearch(e) {
        e.preventDefault();
        
        const type = document.getElementById('nearbyType').value;
        const radius = parseInt(document.getElementById('nearbyRadius').value);
        const maxResults = parseInt(document.getElementById('nearbyMaxResults').value);
        
        this.closeModal('nearbyModal');
        
        try {
            Utils.showLoading();
            
            const results = await API.discovery.search(type, radius, maxResults);
            
            this.displayResults(results.results || []);
            Utils.showToast(`Found ${results.results?.length || 0} places`, 'success');
        } catch (error) {
            Utils.showToast(error.message || 'Search failed', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Handle text search
    async handleTextSearch(e) {
        e.preventDefault();
        
        const query = document.getElementById('textQuery').value;
        const maxResults = parseInt(document.getElementById('textMaxResults').value);
        
        this.closeModal('textModal');
        
        try {
            Utils.showLoading();
            
            const results = await API.discovery.search(query, 50000, maxResults);
            
            this.displayResults(results.results || []);
            Utils.showToast(`Found ${results.results?.length || 0} places`, 'success');
        } catch (error) {
            Utils.showToast(error.message || 'Search failed', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Handle discover
    async handleDiscover() {
        try {
            Utils.showLoading();
            
            const results = await API.discovery.discoverPlaces();
            
            this.displayDiscoverResults(results.results || []);
            Utils.showToast(`Discovered ${results.results?.length || 0} places`, 'success');
        } catch (error) {
            Utils.showToast(error.message || 'Discovery failed', 'error');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Display search results
    displayResults(results) {
        const container = document.getElementById('resultsGrid');
        const resultsContainer = document.getElementById('searchResults');
        
        if (results.length === 0) {
            container.innerHTML = '<div class="empty-state"><i class="fas fa-search"></i><p>No places found</p></div>';
            Utils.show('searchResults');
            return;
        }
        
        container.innerHTML = results.map(place => this.createPlaceCard(place)).join('');
        Utils.show('searchResults');
        
        // Add click listeners
        container.querySelectorAll('.place-card').forEach((card, index) => {
            card.addEventListener('click', () => this.showPlaceDetails(results[index]));
        });
    }
    
    // Display discover results
    displayDiscoverResults(results) {
        const container = document.getElementById('discoverResults');
        
        if (results.length === 0) {
            container.innerHTML = '<div class="empty-state"><i class="fas fa-compass"></i><p>No places found</p></div>';
            return;
        }
        
        container.innerHTML = `<div class="results-grid">${results.map(place => this.createPlaceCard(place)).join('')}</div>`;
        
        // Add click listeners
        container.querySelectorAll('.place-card').forEach((card, index) => {
            card.addEventListener('click', () => this.showPlaceDetails(results[index]));
        });
    }
    
    // Create place card HTML
    createPlaceCard(place) {
        const rating = place.rating ? `⭐ ${place.rating.toFixed(1)}` : 'N/A';
        const distance = place.distance_meters ? Utils.formatDistance(place.distance_meters) : '';
        
        return `
            <div class="place-card" data-place-id="${place.place_id}">
                <div class="place-card-header">
                    <div>
                        <div class="place-name">${place.name}</div>
                        ${place.formatted_address ? `<div class="place-address"><i class="fas fa-map-marker-alt"></i> ${place.formatted_address}</div>` : ''}
                    </div>
                    <div class="place-rating">${rating}</div>
                </div>
                ${place.rating || place.user_ratings_total || distance ? `
                <div class="place-meta">
                    ${place.user_ratings_total ? `<div class="place-meta-item"><i class="fas fa-users"></i> ${place.user_ratings_total} reviews</div>` : ''}
                    ${distance ? `<div class="place-meta-item"><i class="fas fa-route"></i> ${distance}</div>` : ''}
                </div>
                ` : ''}
                <div class="place-card-actions">
                    <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); app.showPlaceDetails('${place.place_id}')">
                        <i class="fas fa-info-circle"></i> Details
                    </button>
                </div>
            </div>
        `;
    }
    
    // Show place details
    async showPlaceDetails(placeIdOrObject) {
        let placeId;
        let placeName;
        
        if (typeof placeIdOrObject === 'object') {
            placeId = placeIdOrObject.place_id;
            placeName = placeIdOrObject.name;
        } else {
            placeId = placeIdOrObject;
            placeName = 'Place Details';
        }
        
        this.currentPlaceId = placeId;
        this.chatHistory = [];
        
        try {
            Utils.showLoading();
            
            // Set modal title
            document.getElementById('placeDetailTitle').textContent = placeName;
            
            // Open modal
            this.openModal('placeDetailsModal');
            
            // Fetch place details
            const details = await API.places.getDetails(placeId);
            
            // Display place info
            this.displayPlaceInfo(details);
            
            // Fetch and display photos
            this.loadPlacePhotos(placeId);
            
            // Trigger knowledge sync (in background)
            this.syncPlaceKnowledge(placeId);
            
            // Clear chat
            document.getElementById('chatMessages').innerHTML = '';
            
            Utils.showToast('Place details loaded', 'success');
        } catch (error) {
            Utils.showToast(error.message || 'Failed to load place details', 'error');
            this.closeModal('placeDetailsModal');
        } finally {
            Utils.hideLoading();
        }
    }
    
    // Display place info
    displayPlaceInfo(details) {
        const infoContainer = document.getElementById('placeInfo');
        
        const html = `
            ${details.rating ? `
            <div class="info-section">
                <h4><i class="fas fa-star"></i> Rating</h4>
                <p>${details.rating.toFixed(1)} out of 5 (${details.user_ratings_total || 0} reviews)</p>
            </div>
            ` : ''}
            
            ${details.formatted_address ? `
            <div class="info-section">
                <h4><i class="fas fa-map-marker-alt"></i> Address</h4>
                <p>${details.formatted_address}</p>
            </div>
            ` : ''}
            
            ${details.formatted_phone_number ? `
            <div class="info-section">
                <h4><i class="fas fa-phone"></i> Phone</h4>
                <p>${details.formatted_phone_number}</p>
            </div>
            ` : ''}
            
            ${details.website ? `
            <div class="info-section">
                <h4><i class="fas fa-globe"></i> Website</h4>
                <p><a href="${details.website}" target="_blank">${details.website}</a></p>
            </div>
            ` : ''}
            
            ${details.opening_hours?.weekday_text ? `
            <div class="info-section">
                <h4><i class="fas fa-clock"></i> Opening Hours</h4>
                <ul>
                    ${details.opening_hours.weekday_text.map(day => `<li>${day}</li>`).join('')}
                </ul>
            </div>
            ` : ''}
            
            ${details.types ? `
            <div class="info-section">
                <h4><i class="fas fa-tag"></i> Categories</h4>
                <p>${details.types.join(', ')}</p>
            </div>
            ` : ''}
        `;
        
        infoContainer.innerHTML = html;
    }
    
    // Load place photos
    async loadPlacePhotos(placeId) {
        const photosContainer = document.getElementById('placePhotos');
        photosContainer.innerHTML = '<div class="loading-inline"><div class="loading-spinner"></div></div>';
        
        try {
            const data = await API.places.getPhotos(placeId, 800, 600);
            
            if (data.photos && data.photos.length > 0) {
                photosContainer.innerHTML = data.photos.map(photo => 
                    `<img src="${photo.url}" alt="Place photo" class="place-photo" />`
                ).join('');
            } else {
                photosContainer.innerHTML = '<div class="empty-state"><i class="fas fa-image"></i><p>No photos available</p></div>';
            }
        } catch (error) {
            console.error('Failed to load photos:', error);
            photosContainer.innerHTML = '<div class="empty-state"><i class="fas fa-image"></i><p>Photos not available</p></div>';
        }
    }
    
    // Sync place knowledge (background)
    async syncPlaceKnowledge(placeId) {
        try {
            await API.knowledge.syncPlace(placeId);
            console.log('Knowledge synced for place:', placeId);
        } catch (error) {
            console.error('Knowledge sync failed:', error);
        }
    }
    
    // Handle chat
    async handleChat(e) {
        e.preventDefault();
        
        const input = document.getElementById('chatInput');
        const question = input.value.trim();
        
        if (!question || !this.currentPlaceId) return;
        
        // Clear input
        input.value = '';
        
        // Add user message
        this.addChatMessage(question, 'user');
        
        try {
            // Show loading
            this.addChatMessage('Thinking...', 'assistant', true);
            
            // Ask question
            const response = await API.qa.askQuestion(this.currentPlaceId, question);
            
            // Remove loading
            const messages = document.getElementById('chatMessages');
            messages.removeChild(messages.lastChild);
            
            // Add assistant message
            this.addChatMessage(response.answer, 'assistant');
            
            // Store in history
            this.chatHistory.push({ question, answer: response.answer });
        } catch (error) {
            // Remove loading
            const messages = document.getElementById('chatMessages');
            messages.removeChild(messages.lastChild);
            
            this.addChatMessage('Sorry, I could not answer that question.', 'assistant');
            Utils.showToast(error.message || 'Failed to get answer', 'error');
        }
    }
    
    // Add chat message
    addChatMessage(text, sender, isLoading = false) {
        const messagesContainer = document.getElementById('chatMessages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${sender}`;
        
        messageDiv.innerHTML = `
            <div class="message-bubble">${text}</div>
            ${!isLoading ? `<div class="message-time">${new Date().toLocaleTimeString()}</div>` : ''}
        `;
        
        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
    
    // Clear results
    clearResults() {
        document.getElementById('resultsGrid').innerHTML = '';
        Utils.hide('searchResults');
    }
}

// Initialize app
const app = new GeoMapApp();

// Close user dropdown when clicking outside
document.addEventListener('click', (e) => {
    const userMenu = document.querySelector('.nav-user');
    const dropdown = document.getElementById('userDropdown');
    
    if (userMenu && !userMenu.contains(e.target)) {
        dropdown.classList.remove('show');
    }
});
