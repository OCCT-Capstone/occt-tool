// Small global helper used by all pages.
(function (w, d) {
  const K = { THEME:'occt.theme', MODE:'occt.apiMode' };

  const get = (k, def) => localStorage.getItem(k) ?? def;
  const set = (k, v)   => localStorage.setItem(k, v);

  // Apply theme ASAP (prevents flash)
  function applyThemeEarly() {
    d.documentElement.classList.toggle('theme-dark', get(K.THEME, 'light') === 'dark');
  }

  // Build API path depending on mode
  // live -> /api/live, sample -> /api/sample
  function api(path) {
    const mode = get(K.MODE, 'sample');
    return mode === 'live' ? `/api/live${path}` : `/api/sample${path}`;
  }

  // ---- AU Date/Time helpers (AEST/AEDT) ----
  const AU_TZ = 'Australia/Sydney';
  function formatDateTimeAU(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    // Example: 11/09/2025 14:07 (DD/MM/YYYY HH:MM 24h)
    return d.toLocaleString('en-AU', {
      timeZone: AU_TZ,
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).replace(',', '');
  }
  function formatDateAU(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    // Example: 11/09/2025 (DD/MM/YYYY)
    return d.toLocaleDateString('en-AU', {
      timeZone: AU_TZ,
      day: '2-digit', month: '2-digit', year: 'numeric'
    });
  }
  function formatTimeAU(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    // Example: 14:07
    return d.toLocaleTimeString('en-AU', {
      timeZone: AU_TZ,
      hour: '2-digit', minute: '2-digit', hour12: false
    });
  }

  w.occt = { K, get, set, api, applyThemeEarly, formatDateTimeAU, formatDateAU, formatTimeAU };
  applyThemeEarly();
})(window, document);

