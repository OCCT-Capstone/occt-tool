// static/js/settings.js
(function () {
  // Guarded access to occt keys (fallback if site.js path is wrong)
  const occt = window.occt || { K: { THEME: 'occt.theme', MODE: 'occt.apiMode' }, get: ()=>null, set: ()=>{} };
  const K = occt.K;

  const $ = (s) => document.querySelector(s);
  const themeDark = $('#themeDark');
  const apiMode   = $('#apiMode');      // <select id="apiMode"> with values "sample" | "live"
  const form      = $('#settingsForm');
  const toast     = $('#toast');
  const resetBtn  = $('#resetBtn');
  const logoutBtn = $('#logoutBtn');
  const rescanBtn = $('#rescanBtn');    // <button id="rescanBtn">Rescan</button>
  const rescanMsg = $('#rescanStatus'); // optional <div id="rescanStatus"></div>

  const DEFAULTS = {
    [K.THEME]: 'light',
    [K.MODE]:  'sample',
  };

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.hidden = true), 1400);
  }

  function setText(el, v) { if (el) el.textContent = v; }

  function load() {
    const theme = localStorage.getItem(K.THEME) || DEFAULTS[K.THEME];
    const mode  = localStorage.getItem(K.MODE)  || DEFAULTS[K.MODE];

    if (themeDark) themeDark.checked = (theme === 'dark');
    if (apiMode)   apiMode.value     = mode;

    // apply theme immediately
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
  }

  // Instant theme switching — no Save required
  function applyThemeFromToggle() {
    const dark = !!themeDark?.checked;
    localStorage.setItem(K.THEME, dark ? 'dark' : 'light');
    document.documentElement.classList.toggle('theme-dark', dark);
    showToast(`Theme: ${dark ? 'Dark' : 'Light'}`);
  }

  // Persist data source immediately when dropdown changes
  function onModeChange() {
    const mode = apiMode?.value === 'live' ? 'live' : 'sample';
    localStorage.setItem(K.MODE, mode);
    showToast(`Data source: ${mode.toUpperCase()}`);
  }

  // Save ONLY the data source (theme already persisted on toggle)
  function save(e) {
    e?.preventDefault?.();
    if (apiMode) localStorage.setItem(K.MODE, apiMode.value);
    showToast('Data source saved');
  }

  function resetAll() {
    Object.entries(DEFAULTS).forEach(([k, v]) => localStorage.setItem(k, v));
    load(); // re-apply UI + theme
    showToast('Defaults restored');
  }

  // ---- Rescan: POST to current mode's /rescan ----
  async function doRescan() {
    if (!rescanBtn) return;
    rescanBtn.disabled = true;
    const orig = rescanBtn.textContent;
    rescanBtn.textContent = 'Rescanning…';
    setText(rescanMsg, '');

    try {
      // Use the global helper to build the correct base (/api/sample or /api/live)
      const url = (window.occt && window.occt.api) ? window.occt.api('/rescan') : '/api/rescan';
      const resp = await fetch(url, { method: 'POST' });
      const body = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        const msg = body?.message || `Rescan failed (${resp.status})`;
        showToast(msg);
        setText(rescanMsg, msg);
      } else {
        // For sample mode we return ingested + unique counts; for live mode we return 501 for now
        const ing = (body?.ingested ?? '—');
        const tot = (body?.total_unique ?? '—');
        const fail= (body?.failed_unique ?? '—');
        const msg = `Rescan OK. Ingested: ${ing}, Total unique: ${tot}, Failed: ${fail}`;
        showToast('Rescan complete');
        setText(rescanMsg, msg);
      }
    } catch (e) {
      const msg = `Rescan error: ${e}`;
      showToast('Rescan error');
      setText(rescanMsg, msg);
    } finally {
      rescanBtn.textContent = orig;
      rescanBtn.disabled = false;
    }
  }

  // ---- Real logout ----
  async function logoutNow() {
    try {
      await fetch('/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch' }
      });
    } catch (_) {
      // ignore
    } finally {
      window.location.replace('/login');
    }
  }

  // ---- Wire events ----
  themeDark?.addEventListener('change', applyThemeFromToggle);
  apiMode?.addEventListener('change', onModeChange);
  form?.addEventListener('submit', save);
  resetBtn?.addEventListener('click', resetAll);
  logoutBtn?.addEventListener('click', logoutNow);
  rescanBtn?.addEventListener('click', doRescan);

  // ---- Initial ----
  load();
})();
