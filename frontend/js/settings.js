// static/js/settings.js
(function () {
  // Guarded access to occt keys (fallback if site.js path is wrong)
  const occt = window.occt || { K: { THEME: 'occt.theme', MODE: 'occt.apiMode' } };
  const K = occt.K;

  const $ = (s) => document.querySelector(s);
  const themeDark = $('#themeDark');
  const apiMode   = $('#apiMode');
  const form      = $('#settingsForm');
  const toast     = $('#toast');
  const resetBtn  = $('#resetBtn');
  const logoutBtn = $('#logoutBtn');

  const DEFAULTS = {
    [K.THEME]: 'light',
    [K.MODE]:  'sample',
  };

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.hidden = true), 1200);
  }

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

  // ---- Real logout ----
  async function logoutNow() {
    try {
      const res = await fetch('/auth/logout', {
        method: 'POST',
        credentials: 'same-origin', // include session cookie
        headers: { 'X-Requested-With': 'fetch' }
      });
      // Even if non-200, clear client state and go to /login
    } catch (_) {
      // ignore network errors; still navigate away
    } finally {
      // Optional: nuke any local client state as well
      // localStorage.clear(); // uncomment if you want a totally clean slate
      window.location.replace('/login');
    }
  }

  // ---- Wire events ----
  themeDark?.addEventListener('change', applyThemeFromToggle);
  form?.addEventListener('submit', save);
  resetBtn?.addEventListener('click', resetAll);
  logoutBtn?.addEventListener('click', logoutNow); // <-- single, correct handler

  // ---- Initial ----
  load();
})();
