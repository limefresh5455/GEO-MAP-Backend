// ============================================
// Modern GeoMap API Service
// ============================================

const API = {
    // Base request handler
    async request(endpoint, options = {}) {
        const url = `${CONFIG.API_BASE_URL}${endpoint}`;
        const token = Utils.getToken();
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        try {
            const response = await fetch(url, {
                ...options,
                headers
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || data.message || 'Request failed');
            }
            
            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },
    
    // GET request
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },
    
    // POST request
    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },
    
    // PUT request
    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },
    
    // DELETE request
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },
    
    // === Auth APIs ===
    auth: {
        async register(name, email, password) {
            return API.post('/auth/register', {
                full_name: name,
                email,
                password
            });
        },
        
        async login(email, password) {
            // Backend expects JSON with 'email' and 'password' fields
            return API.post('/auth/login', {
                email,
                password
            });
        },
        
        async getMe() {
            return API.get('/auth/me');
        }
    },
    
    // === Location APIs ===
    location: {
        async setGPS(latitude, longitude) {
            return API.post('/locations/gps', {
                latitude,
                longitude
            });
        },
        
        async getCurrent() {
            return API.get('/locations/current');
        }
    },
    
    // === Discovery APIs ===
    discovery: {
        async search(query, radius, maxResults) {
            return API.post('/discovery/search', {
                query,
                radius_meters: radius,
                max_results: maxResults
            });
        },
        
        async discoverPlaces() {
            // Get current location
            const location = Utils.getLocation();
            if (!location) {
                throw new Error('Location not set');
            }
            
            // Use discovery search with generic query
            return API.post('/discovery/search', {
                query: 'popular places',
                radius_meters: 5000,
                max_results: 15
            });
        }
    },
    
    // === Place APIs ===
    places: {
        async getDetails(placeId) {
            return API.get(`/places/${placeId}`);
        },
        
        async getPhotos(placeId, maxWidth = 800, maxHeight = 600) {
            try {
                const response = await fetch(
                    `${CONFIG.API_BASE_URL}/place-photos/${placeId}?max_width=${maxWidth}&max_height=${maxHeight}`,
                    {
                        headers: {
                            'Authorization': `Bearer ${Utils.getToken()}`
                        }
                    }
                );
                
                if (!response.ok) {
                    throw new Error('Failed to fetch photos');
                }
                
                const data = await response.json();
                return data;
            } catch (error) {
                console.error('Photo fetch error:', error);
                return { photos: [] };
            }
        }
    },
    
    // === Knowledge Sync API ===
    knowledge: {
        async syncPlace(placeId) {
            return API.post(`/knowledge/sync/${placeId}`);
        }
    },
    
    // === Place Q&A APIs ===
    qa: {
        async askQuestion(placeId, question, sessionId = null) {
            const payload = { question };
            if (typeof sessionId === 'string' && sessionId.length === 24) {
                payload.session_id = sessionId;
            }
            return API.post(`/places/${placeId}/question`, payload);
        },
        
        async listSessions(page = 1, pageSize = 10, filters = {}) {
            const params = new URLSearchParams({
                page: page,
                page_size: pageSize
            });
            if (filters.placeId) params.append('place_id', filters.placeId);
            if (filters.search) params.append('search', filters.search);
            if (filters.sort) params.append('sort', filters.sort);
            
            return API.get(`/places/qa/sessions?${params.toString()}`);
        },
        
        async getSession(sessionId, page = 1, pageSize = 10) {
            return API.get(`/places/qa/sessions/${sessionId}?page=${page}&page_size=${pageSize}`);
        },
        
        async deleteSessions(sessionIds) {
            const params = sessionIds.map(id => `session_ids=${id}`).join('&');
            return API.delete(`/places/qa/sessions?${params}`);
        },
        
        async updateSession(sessionId, data) {
            return API.request(`/places/qa/sessions/${sessionId}`, {
                method: 'PATCH',
                body: JSON.stringify(data)
            });
        }
    },
    
    // === Routes APIs ===
    routes: {
        async compute(destinationPlaceId, options = {}) {
            const location = Utils.getLocation();
            if (!location) {
                throw new Error('Location not set');
            }
            
            const payload = {
                origin: {
                    latitude: location.latitude,
                    longitude: location.longitude
                },
                destination_place_id: destinationPlaceId,
                travel_mode: options.travelMode || 'DRIVE',
                ...options
            };
            
            return API.post('/routes/compute', payload);
        }
    }
};
