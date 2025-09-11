// static/js/settings.js
(function () {
  const occt = window.occt || { K: { THEME: 'occt.theme', MODE: 'occt.apiMode' } };
  const K = occt.K;

  const $ = (s) => document.querySelector(s);
  const themeDark = $('#themeDark');
  const apiMode   = $('#apiMode');
  const toast     = $('#toast');
  const resetBtn  = $('#resetBtn');
  const logoutBtn = $('#logoutBtn');
  const rescanBtn = $('#rescanBtn');
  const rescanMsg = $('#rescanStatus');
  const reportBtn   = $('#reportBtn');
  const reportDlBtn = $('#reportDlBtn');

  const DEFAULTS = { [K.THEME]: 'light', [K.MODE]: 'sample' };

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.hidden = true), 1400);
  }
  const setText = (el, v) => { if (el) el.textContent = v; };

  function load() {
    const theme = localStorage.getItem(K.THEME) || DEFAULTS[K.THEME];
    const mode  = localStorage.getItem(K.MODE)  || DEFAULTS[K.MODE];
    if (themeDark) themeDark.checked = (theme === 'dark');
    if (apiMode)   apiMode.value     = mode;
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
  }

  function applyThemeFromToggle() {
    const dark = !!themeDark?.checked;
    localStorage.setItem(K.THEME, dark ? 'dark' : 'light');
    document.documentElement.classList.toggle('theme-dark', dark);
    showToast(`Theme: ${dark ? 'Dark' : 'Light'}`);
  }

  function onModeChange() {
    const mode = apiMode?.value === 'live' ? 'live' : 'sample';
    localStorage.setItem(K.MODE, mode);
    showToast(`Data source: ${mode.toUpperCase()}`);
  }

  function resetAll() {
    Object.entries(DEFAULTS).forEach(([k, v]) => localStorage.setItem(k, v));
    load();
    showToast('Defaults restored');
  }

  async function doRescan() {
    if (!rescanBtn) return;
    rescanBtn.disabled = true;
    const orig = rescanBtn.textContent;
    rescanBtn.textContent = 'Rescanning…';
    setText(rescanMsg, '');

    try {
      const url = (window.occt && window.occt.api) ? window.occt.api('/rescan') : '/api/sample/rescan';
      const resp = await fetch(url, { method: 'POST' });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const msg = body?.message || `Rescan failed (${resp.status})`;
        showToast(msg); setText(rescanMsg, msg);
      } else {
        const ing = (body?.ingested ?? '—');
        const tot = (body?.total_unique ?? '—');
        const fail= (body?.failed_unique ?? '—');
        setText(rescanMsg, `Rescan OK. Ingested: ${ing}, Total unique: ${tot}, Failed: ${fail}`);
        showToast('Rescan complete');
      }
    } catch (e) {
      const msg = `Rescan error: ${e}`;
      showToast('Rescan error'); setText(rescanMsg, msg);
    } finally {
      rescanBtn.textContent = orig;
      rescanBtn.disabled = false;
    }
  }

  function openReport() {
    const url = (window.occt && window.occt.api) ? window.occt.api('/report') : '/api/sample/report';
    window.open(url, '_blank');
  }
  function downloadReport() {
    const base = (window.occt && window.occt.api) ? window.occt.api('/report') : '/api/sample/report';
    window.location.href = `${base}?download=1`;
  }

  async function logoutNow() {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } });
    } catch (_) { /* ignore */ }
    finally { window.location.replace('/login'); }
  }

  // Wire events
  themeDark?.addEventListener('change', applyThemeFromToggle);
  apiMode?.addEventListener('change', onModeChange);
  resetBtn?.addEventListener('click', resetAll);
  logoutBtn?.addEventListener('click', logoutNow);
  rescanBtn?.addEventListener('click', doRescan);
  reportBtn?.addEventListener('click', openReport);
  reportDlBtn?.addEventListener('click', downloadReport);

  load();
})();
