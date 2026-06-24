/**
 * GeoMap API Tester – Application Logic v2
 * Handles all API interactions, auth, and UI state management.
 *
 * Fixes applied:
 *  U1: highlightJSON() — safe regex that doesn't corrupt string values
 *  U3: WebSocket wsConnection reset on auth failure
 *  U4: Content-Type header only on requests with body
 *  U5: Toast container — ensure singleton creation
 *  U7: Better token validation — show "Invalid token" for non-JWT
 *  U9: Robust WS_BASE URL construction behind proxies
 *  U10: localStorage instead of sessionStorage for token persistence
 */
(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════════
  // Configuration
  // ═══════════════════════════════════════════════════════════════════════════

  const API_BASE = '/api/v1';
  // U9 FIX: Build WS URL robustly — handle proxy/reverse-proxy setups
  const WS_PROTO = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const WS_BASE = WS_PROTO + '//' + location.host + '/ws/chat';
  const AUTH_TOKEN_KEY = 'geomap_api_token';

  // ── State ───────────────────────────────────────────────────────────────
  // U10 FIX: Use localStorage (persists across tabs) instead of sessionStorage
  let authToken = localStorage.getItem(AUTH_TOKEN_KEY) || '';
  let wsConnection = null;

  // ── DOM Ready ───────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    initAuth();
    initEvents();
    initSearch();
    initWSPanel();
    updateConnectionStatus();
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════════════════════════

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }

  function $$(sel, ctx) { return Array.from((ctx || document).querySelectorAll(sel)); }

  function getToken() { return authToken; }

  function setToken(token) {
    authToken = token;
    if (token) {
      localStorage.setItem(AUTH_TOKEN_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_KEY);
    }
    updateAuthUI();
  }

  // U4 FIX: Only add Content-Type when there's a request body
  function getHeaders(hasBody) {
    const h = {};
    if (hasBody) h['Content-Type'] = 'application/json';
    if (authToken) h['Authorization'] = 'Bearer ' + authToken;
    return h;
  }

  function formatTime(ts) {
    return new Date(ts).toLocaleTimeString('en-US', { hour12: false }) + '.' + String(ts % 1000).padStart(3, '0');
  }

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // U1 FIX: Safe JSON highlighting that doesn't corrupt string values
  function highlightJSON(obj) {
    const json = JSON.stringify(obj, null, 2);
    // Escape HTML entities first
    const escaped = json
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    // Apply token-based highlighting (safer than raw regex on entire string)
    return escaped
      .replace(/(&quot;(?:\\[\s\S]|[^&"])*&quot;)\s*:/g, '<span class="json-key">$1</span>:')
      .replace(/: (&quot;(?:\\[\s\S]|[^&"])*&quot;)/g, ': <span class="json-string">$1</span>')
      .replace(/: (\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
      .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
      .replace(/: (null)/g, ': <span class="json-null">$1</span>');
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Toast Notifications
  // ═══════════════════════════════════════════════════════════════════════════

  // U5 FIX: Single container reference created once
  let _toastContainer = null;

  function getToastContainer() {
    if (!_toastContainer) {
      _toastContainer = $('#toast-container');
      if (!_toastContainer) {
        _toastContainer = document.createElement('div');
        _toastContainer.id = 'toast-container';
        _toastContainer.className = 'toast-container';
        document.body.appendChild(_toastContainer);
      }
    }
    return _toastContainer;
  }

  function showToast(message, type) {
    type = type || 'info';
    const container = getToastContainer();
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.innerHTML =
      '<span class="toast-icon">' + (icons[type] || '') + '</span>' +
      '<span class="toast-message">' + escapeHtml(message) + '</span>' +
      '<span class="toast-close">&times;</span>';

    toast.querySelector('.toast-close').onclick = () => toast.remove();
    container.appendChild(toast);

    setTimeout(() => {
      if (toast.parentNode) toast.remove();
    }, 5000);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Connection Status
  // ═══════════════════════════════════════════════════════════════════════════

  function updateConnectionStatus() {
    const dots = $$('.connection-dot');
    fetch(API_BASE + '/auth/me', {
      headers: getHeaders(false),
    }).then(r => {
      const online = r.status !== 401 && r.status !== 503;
      dots.forEach(d => {
        d.className = 'connection-dot ' + (online ? 'online' : 'offline');
      });
    }).catch(() => {
      dots.forEach(d => { d.className = 'connection-dot offline'; });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Auth UI
  // ═══════════════════════════════════════════════════════════════════════════

  function initAuth() {
    const input = $('#auth-token-input');
    if (input) {
      input.value = authToken;
      input.placeholder = 'Paste your Bearer token here...';
      input.addEventListener('input', () => {
        setToken(input.value.trim());
      });
    }
    updateAuthUI();
  }

  // U7 FIX: Better token validation — distinguish "invalid" from "valid unknown"
  function updateAuthUI() {
    const status = $('.token-status');
    if (!status) return;

    if (!authToken) {
      status.className = 'token-status empty';
      status.textContent = 'No token';
      return;
    }

    // Try to decode JWT payload to check expiry
    try {
      const parts = authToken.split('.');
      if (parts.length !== 3) {
        status.className = 'token-status invalid';
        status.textContent = 'Invalid token format';
        return;
      }
      // Validate base64url encoding before decoding
      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const payload = JSON.parse(atob(base64));
      const exp = payload.exp * 1000;
      const now = Date.now();
      if (exp < now) {
        status.className = 'token-status invalid';
        status.textContent = 'Token expired';
      } else {
        const mins = Math.round((exp - now) / 60000);
        if (mins > 60) {
          const hours = Math.floor(mins / 60);
          status.className = 'token-status valid';
          status.textContent = 'Valid (' + hours + 'h ' + (mins % 60) + 'm)';
        } else {
          status.className = 'token-status valid';
          status.textContent = 'Valid (' + mins + 'm)';
        }
      }
    } catch (e) {
      status.className = 'token-status invalid';
      status.textContent = 'Invalid token';
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Search / Filter (U8: with visual highlighting)
  // ═══════════════════════════════════════════════════════════════════════════

  function initSearch() {
    const input = $('#section-search');
    if (!input) return;
    input.addEventListener('input', () => {
      const q = input.value.toLowerCase().trim();
      // Track if any section has a match
      let anyMatch = false;

      $$('.api-section').forEach(section => {
        const title = section.querySelector('.section-title').textContent.toLowerCase();
        const endpoints = section.querySelectorAll('.endpoint-card');
        let match = !q;

        if (q) {
          if (title.includes(q)) {
            match = true;
            // Show all endpoints in a matched section
            endpoints.forEach(ep => { ep.style.display = ''; });
          } else {
            endpoints.forEach(ep => {
              const text = ep.textContent.toLowerCase();
              if (text.includes(q)) {
                match = true;
                ep.style.display = '';
              } else {
                ep.style.display = 'none';
              }
            });
          }
        } else {
          // No query — show all endpoints
          endpoints.forEach(ep => { ep.style.display = ''; });
        }

        section.style.display = match ? '' : 'none';
        if (match) anyMatch = true;
      });

      // Show "no results" message if nothing matched
      let noResults = $('#no-results-msg');
      if (q && !anyMatch) {
        if (!noResults) {
          noResults = document.createElement('div');
          noResults.id = 'no-results-msg';
          noResults.className = 'no-results';
          noResults.textContent = '🔍 No endpoints match "' + q + '"';
          document.querySelector('.api-sections').after(noResults);
        }
        noResults.style.display = 'block';
      } else if (noResults) {
        noResults.style.display = 'none';
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Event Binding
  // ═══════════════════════════════════════════════════════════════════════════

  function initEvents() {
    // ── Section Toggle ──
    $$('.api-section-header').forEach(hdr => {
      hdr.addEventListener('click', () => {
        const section = hdr.closest('.api-section');
        section.classList.toggle('expanded');
      });
    });

    // ── Send Request Buttons ──
    $$('[data-endpoint]').forEach(btn => {
      btn.addEventListener('click', () => handleEndpointRequest(btn));
    });

    // ── Sidebar Navigation ──
    $$('.sidebar-link[data-scroll-to]').forEach(link => {
      link.addEventListener('click', () => {
        const id = link.dataset.scrollTo;
        const section = $('#' + id);
        if (section) {
          section.classList.add('expanded');
          section.scrollIntoView({ behavior: 'smooth', block: 'start' });
          $$('.sidebar-link.active').forEach(l => l.classList.remove('active'));
          link.classList.add('active');
        }
      });
    });

    // ── Scroll Tracking ──
    const scrollBtn = $('.scroll-top');
    if (scrollBtn) {
      window.addEventListener('scroll', () => {
        scrollBtn.classList.toggle('visible', window.scrollY > 400);
      });
      scrollBtn.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    // ── Clear Token Button ──
    $$('[data-clear-token]').forEach(btn => {
      btn.addEventListener('click', () => {
        setToken('');
        const input = $('#auth-token-input');
        if (input) input.value = '';
        showToast('Token cleared', 'info');
      });
    });

    // ── Auth Quick Actions ──
    $$('[data-quick-auth]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.quickAuth;
        if (action === 'login' || action === 'signup') {
          $(action + '-section').classList.add('expanded');
          $(action + '-section').scrollIntoView({ behavior: 'smooth' });
        }
      });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // API Request Handler
  // ═══════════════════════════════════════════════════════════════════════════

  async function handleEndpointRequest(btn) {
    const card = btn.closest('.endpoint-card');
    const method = card.dataset.method || 'GET';
    const pathTemplate = card.dataset.path || '';
    const responseViewer = card.querySelector('.response-viewer');
    const responseBody = card.querySelector('.response-body pre');
    const responseError = card.querySelector('.response-error');
    const statusBadge = card.querySelector('.response-status');
    const timeEl = card.querySelector('.response-time');
    const copyBtn = card.querySelector('.copy-btn');

    // ── Disable button & show spinner ──
    btn.disabled = true;
    const origBtnHtml = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span> Sending...';

    try {
      // ── Build URL from path template ──
      let endpointPath = pathTemplate;
      const urlParams = [];

      $$('.param-row', card).forEach(row => {
        const nameEl = row.querySelector('.param-name');
        const input = row.querySelector('input, select');
        if (!nameEl || !input) return;

        let name = nameEl.textContent.trim();
        const val = input.value.trim();

        if (input.dataset.paramIn === 'path') {
          endpointPath = endpointPath.replace('{' + name + '}', val || name);
        } else if (input.dataset.paramIn === 'query') {
          if (val) urlParams.push(name + '=' + encodeURIComponent(val));
        }
      });

      const queryString = urlParams.length ? '?' + urlParams.join('&') : '';
      const url = API_BASE + endpointPath + queryString;

      // ── Build request body ──
      const jsonEditor = card.querySelector('.json-editor');
      let body = null;
      let hasBody = false;
      if (jsonEditor) {
        const raw = jsonEditor.value.trim();
        if (raw) {
          try {
            body = JSON.parse(raw);
            hasBody = true;
          } catch (e) {
            jsonEditor.classList.add('error');
            showToast('Invalid JSON in request body: ' + e.message, 'error');
            btn.disabled = false;
            btn.innerHTML = origBtnHtml;
            return;
          }
          jsonEditor.classList.remove('error');
        }
      }

      // ── Make the request ──
      const startTime = performance.now();
      const fetchOptions = {
        method: method,
        headers: getHeaders(hasBody),
      };
      if (body && ['POST', 'PUT', 'PATCH'].includes(method)) {
        fetchOptions.body = JSON.stringify(body);
      }

      const response = await fetch(url, fetchOptions);
      const elapsed = (performance.now() - startTime).toFixed(1);
      let responseData;

      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        responseData = await response.json();
      } else {
        responseData = { raw: await response.text() };
      }

      // ── Show response ──
      responseViewer.classList.add('visible');
      responseError.textContent = '';

      const statusCode = response.status;
      let statusClass = 'success';
      if (statusCode >= 400) statusClass = 'error';
      else if (statusCode >= 300) statusClass = 'redirect';

      statusBadge.className = 'response-status ' + statusClass;
      statusBadge.textContent = statusCode + ' ' + response.statusText;
      timeEl.textContent = elapsed + 'ms';

      if (responseData) {
        // FastAPI errors come as {"detail": "..."} — check both formats
        const errMsg = responseData.detail || (responseData.error && responseData.error.message) || null;
        if (errMsg) {
          responseError.textContent = 'Error: ' + errMsg;
        }
      }

      responseBody.innerHTML = highlightJSON(responseData);

      // ── Copy button ──
      if (copyBtn) {
        copyBtn.onclick = () => {
          navigator.clipboard.writeText(JSON.stringify(responseData, null, 2))
            .then(() => showToast('Response copied to clipboard', 'success'))
            .catch(() => showToast('Failed to copy', 'error'));
        };
      }

      // ── Auto-extract token from login/signup/refresh responses ──
      if (responseData && responseData.access_token) {
        setToken(responseData.access_token);
        const input = $('#auth-token-input');
        if (input) input.value = responseData.access_token;
        showToast('Token saved from response!', 'success');
      }

    } catch (err) {
      const rv = card.querySelector('.response-viewer');
      if (rv) {
        rv.classList.add('visible');
        const sb = card.querySelector('.response-status');
        sb.className = 'response-status error';
        sb.textContent = 'Network Error';
        const rb = card.querySelector('.response-body pre');
        rb.innerHTML = highlightJSON({ error: err.message });
      }
      showToast('Request failed: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origBtnHtml;
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // WebSocket Panel
  // ═══════════════════════════════════════════════════════════════════════════

  function initWSPanel() {
    const connectBtn = $('#ws-connect');
    const disconnectBtn = $('#ws-disconnect');
    const sendBtn = $('#ws-send');
    const input = $('#ws-input');
    const log = $('#ws-log');
    const statusEl = $('#ws-status');
    const msgType = $('#ws-msg-type');

    if (!connectBtn) return;

    function logEntry(type, msg) {
      const ts = Date.now();
      const entry = document.createElement('div');
      entry.className = 'ws-log-entry';
      entry.innerHTML =
        '<span class="ws-time">' + formatTime(ts) + '</span>' +
        '<span class="ws-' + type + '">' + escapeHtml(msg) + '</span>';
      log.appendChild(entry);
      log.scrollTop = log.scrollHeight;
    }

    function updateWSStatus(state) {
      statusEl.textContent = state;
      statusEl.className = 'ws-status ' + state.toLowerCase();
      connectBtn.disabled = state === 'Connected' || state === 'Connecting';
      disconnectBtn.disabled = state !== 'Connected';
      sendBtn.disabled = state !== 'Connected';
      input.disabled = state !== 'Connected';
    }

    function cleanupWS() {
      wsConnection = null;
    }

    connectBtn.addEventListener('click', () => {
      if (wsConnection) {
        try { wsConnection.close(); } catch (e) { /* ignore */ }
        wsConnection = null;
      }

      if (!authToken) {
        showToast('Set an auth token before connecting WebSocket', 'error');
        return;
      }

      updateWSStatus('Connecting');
      logEntry('info', 'Connecting to WebSocket...');

      try {
        wsConnection = new WebSocket(WS_BASE);

        wsConnection.onopen = () => {
          wsConnection.send(JSON.stringify({
            type: 'auth',
            token: 'Bearer ' + authToken,
          }));
        };

        wsConnection.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            switch (data.type) {
              case 'connected':
                updateWSStatus('Connected');
                logEntry('info', 'Authenticated as user ' + data.user_id);
                break;
              case 'metadata':
                logEntry('received', '[Metadata] session_id=' + (data.session_id || '?') + (data.is_new_session ? ' (new)' : ''));
                break;
              case 'token':
                logEntry('received', '[Token] ' + data.content);
                break;
              case 'done':
                logEntry('received', '[Done]' + (data.title ? ' Title: ' + data.title : ''));
                break;
              case 'error':
                logEntry('error', 'Error: ' + data.message);
                // U3 FIX: Reset connection on auth errors
                if (data.message && (data.message.includes('authentication') || data.message.includes('revoked'))) {
                  updateWSStatus('Disconnected');
                  if (wsConnection) {
                    wsConnection.close();
                    cleanupWS();
                  }
                }
                break;
              default:
                logEntry('received', JSON.stringify(data));
            }
          } catch (e) {
            logEntry('received', event.data);
          }
        };

        wsConnection.onclose = (event) => {
          updateWSStatus('Disconnected');
          logEntry('info', 'Connection closed (code=' + event.code + ')');
          cleanupWS();
        };

        wsConnection.onerror = () => {
          logEntry('error', 'WebSocket error');
          updateWSStatus('Disconnected');
          cleanupWS();
        };
      } catch (err) {
        logEntry('error', 'Connection failed: ' + err.message);
        updateWSStatus('Disconnected');
        cleanupWS();
      }
    });

    disconnectBtn.addEventListener('click', () => {
      if (wsConnection) {
        wsConnection.close();
        cleanupWS();
      }
      updateWSStatus('Disconnected');
    });

    sendBtn.addEventListener('click', () => {
      if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) {
        showToast('WebSocket is not connected', 'error');
        return;
      }

      const raw = input.value.trim();
      if (!raw) return;

      const type = msgType ? msgType.value : 'chat_message';
      let payload;

      try {
        payload = JSON.parse(raw);
      } catch (e) {
        payload = { query: raw };
      }

      const msg = {
        type: type,
        query: payload.query || payload,
        ...(payload.session_id ? { session_id: payload.session_id } : {}),
        ...(payload.place_id ? { place_id: payload.place_id } : {}),
      };

      wsConnection.send(JSON.stringify(msg));
      logEntry('sent', JSON.stringify(msg));
      input.value = '';
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendBtn.click();
      }
    });

    $$('[data-ws-fill]').forEach(btn => {
      btn.addEventListener('click', () => {
        const fill = btn.dataset.wsFill;
        if (fill === 'chat') {
          input.value = JSON.stringify({ query: 'Plan a 2-day trip to Jaipur' }, null, 2);
          if (msgType) msgType.value = 'chat_message';
        } else if (fill === 'place_qa') {
          input.value = JSON.stringify({ query: 'Is this place open on Sunday?', place_id: 'ChIJ...', session_id: null }, null, 2);
          if (msgType) msgType.value = 'place_question';
        }
      });
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Expose for HTML onclick compatibility
  // ═══════════════════════════════════════════════════════════════════════════

  window.handleEndpointRequest = handleEndpointRequest;

})();
