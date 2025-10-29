// frontend/js/site.js
// Small global helper used by all pages.
(function (w, d) {
  const K = { THEME:'occt.theme', MODE:'occt.apiMode', M0DE:'occt.apiM0de' }; // include legacy key

  const get = (k, def) => {
    try { return localStorage.getItem(k) ?? def; } catch { return def; }
  };
  const set = (k, v) => {
    try { localStorage.setItem(k, v); } catch {}
  };

  // --- one-time migration: copy legacy key -> new key if present ---
  (function migrateModeKey(){
    try {
      const oldV = localStorage.getItem(K.M0DE);
      const curV = localStorage.getItem(K.MODE);
      if (oldV && !curV) localStorage.setItem(K.MODE, oldV);
    } catch {}
  })();

  // Centralized mode reader (tolerates legacy/odd keys)
  function getApiModeValue() {
    const keys = [K.MODE, K.M0DE, 'occt.mode', 'occt.aPiMode']; // prefer correct, then legacy/odd
    for (const k of keys) {
      const v = get(k, null);
      if (typeof v === 'string' && v) return v.toLowerCase();
    }
    return 'live'; // sane default
  }

  // Apply theme ASAP (prevents flash)
  function applyThemeEarly() {
    d.documentElement.classList.toggle('theme-dark', get(K.THEME, 'light') === 'dark');
  }

  // Build API path depending on mode
  // live -> /api/live, sample -> /api/sample
  function api(path) {
    return getApiModeValue() === 'live' ? `/api/live${path}` : `/api/sample${path}`;
  }

  // ---- AU Date/Time helpers (AEST/AEDT) ----
  const AU_TZ = 'Australia/Sydney';
  function formatDateTimeAU(iso) {
    if (!iso) return '';
    const dte = new Date(iso);
    try {
      return dte.toLocaleString('en-AU', {
        timeZone: AU_TZ,
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false
      }).replace(',', '');
    } catch {
      const pad = (n)=> (n<10?'0'+n:n);
      return `${dte.getFullYear()}-${pad(dte.getMonth()+1)}-${pad(dte.getDate())} ${pad(dte.getHours())}:${pad(dte.getMinutes())}`;
    }
  }
  function formatDateAU(iso) {
    if (!iso) return '';
    const dte = new Date(iso);
    try {
      return dte.toLocaleDateString('en-AU', {
        timeZone: AU_TZ,
        day: '2-digit', month: '2-digit', year: 'numeric'
      });
    } catch {
      const pad = (n)=> (n<10?'0'+n:n);
      return `${pad(dte.getDate())}/${pad(dte.getMonth()+1)}/${dte.getFullYear()}`;
    }
  }
  function formatTimeAU(iso) {
    if (!iso) return '';
    const dte = new Date(iso);
    try {
      return dte.toLocaleTimeString('en-AU', {
        timeZone: AU_TZ,
        hour: '2-digit', minute: '2-digit', hour12: false
      });
    } catch {
      const pad = (n)=> (n<10?'0'+n:n);
      return `${pad(dte.getHours())}:${pad(dte.getMinutes())}`;
    }
  }

  // ====== Toast UI (site-wide) ======
  function ensureToastHost() {
    let host = d.getElementById('occt-toasts');
    if (!host) {
      host = d.createElement('div');
      host.id = 'occt-toasts';
      host.className = 'toast-stack';
      // minimal inline fallback in case CSS not loaded yet
      host.style.position = host.style.position || 'fixed';
      host.style.top = host.style.top || '12px';
      host.style.right = host.style.right || '12px';
      host.style.zIndex = host.style.zIndex || '9999';
      d.body.appendChild(host);
    }
    return host;
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  }

  function showToast({ title, message, severity='medium', onView=null }) {
    const host = ensureToastHost();

    const el = d.createElement('div');
    el.className = `toast sev-${severity}`;
    el.innerHTML = `
      <div class="toast-bar"></div>
      <div class="toast-content">
        <div class="toast-title">${title ? escapeHtml(title) : 'Detection'}</div>
        <div class="toast-msg">${escapeHtml(message || '')}</div>
      </div>
      <div class="toast-actions">
        <button class="btn btn-sm btn-secondary" data-act="dismiss">Dismiss</button>
        <button class="btn btn-sm" data-act="view">View</button>
      </div>
    `.trim();

    el.addEventListener('click', (ev) => {
      const act = ev.target?.getAttribute?.('data-act');
      if (act === 'dismiss') {
        el.remove();
      } else if (act === 'view') {
        if (typeof onView === 'function') onView();
        else w.location.href = '/detections';
        el.remove();
      }
    });

    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add('in'));     // animate in
    setTimeout(() => el.classList.add('out'), 7000);          // fade at 7s
    setTimeout(() => el.remove(), 8000);                      // remove at 8s
  }

  // ====== SSE gating ======
  function pageWantsSSE() {
    // Default: ON for all pages. Allow opt-out via meta.
    const meta = d.querySelector('meta[name="occt-sse"]');
    if (meta) {
      const v = (meta.getAttribute('content') || '').toLowerCase().trim();
      if (['off','false','0','no'].includes(v)) return false;
      if (['on','true','1','yes'].includes(v))  return true;
    }
    return true; // SSE enabled everywhere unless explicitly disabled
  }

  // ====== Live SSE hookup (single instance, fresh-only) ======
  function initSSE() {
    if (w.__occtSSEInit) return;               // single initializer
    w.__occtSSEInit = true;

    const mode = getApiModeValue();
    if (mode !== 'live') return;               // only listen when in LIVE mode
    if (!pageWantsSSE()) return;               // allow per-page opt-out

    const url = api('/stream');                // /api/live/stream
    let es;
    try {
      es = new EventSource(url, { withCredentials: false });
    } catch (e) {
      console.warn('SSE not available', e);
      return;
    }

    // Store handle globally so we can close it on navigation
    w.__occtSSE = { es, startedAt: Date.now() };

    const connectedAt = w.__occtSSE.startedAt; // drop anything older than page load
    const seen = new Set();                    // optional dedupe if ids show up later

    es.addEventListener('open', () => {
      // console.debug('SSE open');
    });

    es.addEventListener('error', () => {
      // console.warn('SSE error (browser auto-reconnects)');
    });

    es.addEventListener('ping', () => {
      // keepalive from server; nothing to do
    });

    es.addEventListener('detection', (evt) => {
      try {
        const data = JSON.parse(evt.data || '{}');

        // Optional dedupe if server ever adds numeric ids later
        if (data.id && seen.has(data.id)) return;
        if (data.id) {
          seen.add(data.id);
          if (seen.size > 1000) seen.clear();
        }

        // Freshness guard: ignore any detection older than the page load
        const whenMs = Date.parse(data.when || '') || Date.now();
        if (whenMs + 1000 < connectedAt) return;    // allow 1s skew

        const sev = (data.severity || 'medium').toLowerCase();
        const title = `New ${sev.toUpperCase()} detection`;
        const parts = [];
        if (data.rule_id) parts.push(`[${String(data.rule_id).toUpperCase()}]`);
        if (data.summary) parts.push(String(data.summary));
        if (data.host) parts.push(`Host: ${data.host}`);
        if (data.account) parts.push(`Account: ${data.account}`);
        if (data.ip && data.ip !== 'N/A') parts.push(`IP: ${data.ip}`);

        showToast({
          title,
          message: parts.join(' · '),
          severity: sev,
          onView: () => { w.location.href = '/detections'; }
        });
      } catch (e) {
        console.warn('Bad detection payload', e);
      }
    });

    // Close the stream on navigation
    w.addEventListener('beforeunload', () => {
      try { w.__occtSSE?.es?.close(); } catch {}
    }, { once: true });
  }

  // expose minimal API (keep a compatibility alias)
  w.occt = {
    K, get, set, api, applyThemeEarly,
    formatDateTimeAU, formatDateAU, formatTimeAU,
    initSSE, showToast,
    notifyToast: showToast   // <-- compat for any older code expecting this name
  };

  // run immediately (theme) and start SSE ASAP
  applyThemeEarly();
  initSSE();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSSE);
  }
})(window, document);
