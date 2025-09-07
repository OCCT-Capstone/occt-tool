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
  function api(path) {
    const mode = get(K.MODE, 'sample');
    return mode === 'live' ? `/api${path}` : `/api/sample${path}`;
  }

  w.occt = { K, get, set, api, applyThemeEarly };
  applyThemeEarly();
})(window, document);
