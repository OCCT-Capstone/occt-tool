// frontend/js/loader.js
// Global loader overlay for /api/* requests.
// - Safe in <head> or end-of-<body>
// - No external CSS edits; injects its own scoped, theme-aware styles
// - Shows after 200ms to avoid flicker; hides when all API calls settle
// - Opt-out per request with header: 'X-OCCT-No-Loader': '1'

(() => {
  const OVERLAY_ID = 'occt-loading-overlay';
  const STYLE_ID = 'occt-loading-style';
  let inflight = 0;
  let showTimer = null;

  // Inject styles immediately (head exists even in <head> execution)
  (function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
:root {
  --occt-bg: rgba(255,255,255,.65);
  --occt-panel: #ffffff;
  --occt-fg: #1f2937;
  --occt-border: rgba(0,0,0,.08);
  --occt-shadow: 0 6px 24px rgba(0,0,0,.12);
  --occt-accent: #3b82f6;
}
:root[data-theme="dark"], body[data-theme="dark"], body.dark, body.theme-dark {
  --occt-bg: rgba(0,0,0,.45);
  --occt-panel: #111827;
  --occt-fg: #e5e7eb;
  --occt-border: rgba(255,255,255,.14);
  --occt-shadow: 0 10px 30px rgba(0,0,0,.6);
  --occt-accent: #60a5fa;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]),
  body:not([data-theme]):not(.dark):not(.theme-dark) {
    --occt-bg: rgba(0,0,0,.45);
    --occt-panel: #111827;
    --occt-fg: #e5e7eb;
    --occt-border: rgba(255,255,255,.14);
    --occt-shadow: 0 10px 30px rgba(0,0,0,.6);
    --occt-accent: #60a5fa;
  }
}
#${OVERLAY_ID} {
  position: fixed; inset: 0; z-index: 9999;
  pointer-events: none; opacity: 0; transition: opacity .14s ease-in-out;
}
#${OVERLAY_ID}.is-visible { pointer-events: auto; opacity: 1; }
#${OVERLAY_ID} .occt-backdrop { position: absolute; inset: 0; background: var(--occt-bg); backdrop-filter: blur(1px); }
#${OVERLAY_ID} .occt-box {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
  display: flex; gap: .75rem; align-items: center; padding: .75rem 1rem;
  background: var(--occt-panel); color: var(--occt-fg);
  border: 1px solid var(--occt-border); border-radius: .75rem; box-shadow: var(--occt-shadow); font-size: .95rem;
}
#${OVERLAY_ID} .occt-spin {
  width: 20px; height: 20px; border: 3px solid rgba(0,0,0,.12);
  border-top-color: var(--occt-accent); border-radius: 50%; animation: occt-rot .75s linear infinite;
}
@media (prefers-color-scheme: dark) {
  #${OVERLAY_ID} .occt-spin { border-color: rgba(255,255,255,.12); }
}
@keyframes occt-rot { to { transform: rotate(360deg); } }
#${OVERLAY_ID} .occt-bar {
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, rgba(0,0,0,0) 0%, var(--occt-accent) 50%, rgba(0,0,0,0) 100%);
  background-size: 200% 100%; animation: occt-bar 1.1s ease-in-out infinite; opacity: .9;
}
@keyframes occt-bar { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { #${OVERLAY_ID} .occt-spin, #${OVERLAY_ID} .occt-bar { animation: none; } }
`.trim();
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.type = 'text/css';
    style.appendChild(document.createTextNode(css));
    (document.head || document.documentElement).appendChild(style);
  })();

  // Create overlay, but only when <body> exists
  function ensureOverlay(cb) {
    const existing = document.getElementById(OVERLAY_ID);
    if (existing) { if (cb) cb(existing); return existing; }
    const create = () => {
      if (document.getElementById(OVERLAY_ID)) { if (cb) cb(document.getElementById(OVERLAY_ID)); return; }
      const wrap = document.createElement('div');
      wrap.id = OVERLAY_ID;
      wrap.setAttribute('aria-hidden', 'true');
      wrap.innerHTML = `
        <div class="occt-backdrop"></div>
        <div class="occt-box" role="status" aria-live="polite">
          <div class="occt-spin" aria-hidden="true"></div>
          <div>Loading…</div>
        </div>
        <div class="occt-bar"></div>
      `;
      document.body.appendChild(wrap);
      if (cb) cb(wrap);
    };
    if (document.body) create();
    else document.addEventListener('DOMContentLoaded', create, { once: true });
  }

  function showOverlay() {
    ensureOverlay(el => el.classList.add('is-visible'));
  }
  function hideOverlay() {
    const el = document.getElementById(OVERLAY_ID);
    if (el) el.classList.remove('is-visible');
  }

  function start() {
    if (inflight === 0) showTimer = setTimeout(showOverlay, 200);
    inflight++;
  }
  function stop() {
    inflight = Math.max(0, inflight - 1);
    if (inflight === 0) {
      if (showTimer) { clearTimeout(showTimer); showTimer = null; }
      hideOverlay();
    }
  }

  const origFetch = window.fetch ? window.fetch.bind(window) : null;
  if (!origFetch) return;

  window.fetch = function(resource, init = {}) {
    try {
      const u = new URL(typeof resource === 'string' ? resource : (resource && resource.url) || '', window.location.href);
      const isApi = u.pathname.startsWith('/api/');
      const headers = new Headers((init && init.headers) || (resource && resource.headers) || {});
      const noLoader = headers.get('X-OCCT-No-Loader') === '1';
      if (isApi && !noLoader) start();
      const nextInit = Object.assign({}, init, { headers });
      return origFetch(resource, nextInit)
        .then(res => res)
        .catch(err => { throw err; })
        .finally(() => { if (isApi && !noLoader) stop(); });
    } catch {
      // if URL parsing throws (very old browsers), just call through
      return origFetch(resource, init);
    }
  };

  // optional: expose simple controls
  window.occt = window.occt || {};
  window.occt.loading = { show: showOverlay, hide: hideOverlay, inflight: () => inflight };
})();
