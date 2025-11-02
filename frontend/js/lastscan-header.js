// frontend/js/lastscan-header.js
(function () {
  const occt = window.occt || { K: { MODE: 'occt.apiMode' } };
  const K = occt.K;

  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch (_) { return 'live'; }
  }
  function pageApi(path) {
    return (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;
  }
  function fmt(iso) {
    if (!iso) return '—';
    try { return (window.occt?.formatDateTimeAU ? window.occt.formatDateTimeAU(iso) : iso); }
    catch { return iso; }
  }

  async function refreshHint() {
    const hint = document.getElementById('lastScanHeaderHint');
    if (!hint) return;
    try {
      const res = await fetch(pageApi('/last-scan'), { headers: { 'X-OCCT-No-Loader': '1' } });
      const j = await res.json();
      const textEl = hint.querySelector('.text');
      if (textEl) textEl.textContent = 'Last scan: ' + (j?.has_data ? fmt(j.completed_at) : '—');
      hint.hidden = false;
    } catch (_) {

    }
  }

  refreshHint();
  window.addEventListener('storage', (e) => {
    if (e.key === K.MODE) refreshHint();
  });
})();
