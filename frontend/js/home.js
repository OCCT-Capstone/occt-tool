// frontend/js/home.js
(function () {
  const occt = window.occt || { K: { MODE: 'occt.apiMode' } };
  const K = occt.K;
  const $ = (s, r = document) => r.querySelector(s);

  const viewBtn = $('#viewLastBtn');
  const newBtn  = $('#newScanBtn');
  const eventsEl = $('#lastScanEvents');
  const failEl   = $('#lastScanFailed');

  let hasLastScan = false;

  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch { return 'live'; }
  }
  try { if (!localStorage.getItem(K.MODE)) localStorage.setItem(K.MODE, 'live'); } catch {}

  function pageApi(path) {
    return (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;
  }

  function updateScanControls() {
    const isSample = getMode() === 'sample';
    if (newBtn) {
      newBtn.disabled = isSample;
      newBtn.title = isSample ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.' : '';
      newBtn.classList.toggle('is-disabled', isSample);
    }
  }

  async function loadLastScan() {
    try {
      updateScanControls();
      const res = await fetch(pageApi('/last-scan'), {
        headers: { 'X-OCCT-No-Loader': '1' },
        credentials: 'include'
      });
      if (!res.ok) return;

      const j = await res.json();
      hasLastScan = !!j?.has_data;

      if (viewBtn) {
        if (hasLastScan) {
          viewBtn.removeAttribute('disabled');
          viewBtn.title = 'Open Dashboard to view the most recent results';
        } else {
          viewBtn.setAttribute('disabled', 'true');
          viewBtn.title = 'No previous scan yet — run a scan first';
        }
      }

      if (hasLastScan) {
        if (eventsEl && typeof j.event_count !== 'undefined') eventsEl.textContent = j.event_count;
        if (failEl   && typeof j.failed_count  !== 'undefined') failEl.textContent  = j.failed_count;
      } else {
        if (eventsEl) eventsEl.textContent = '—';
        if (failEl)   failEl.textContent   = '—';
      }
    } catch { /* silent */ }
  }

  async function startNewScan() {
    if (getMode() === 'sample') return; // extra guard
    if (newBtn) newBtn.disabled = true;

    window.occt?.loading?.show?.();
    try {
      const resp = await fetch(pageApi('/rescan') + '?wait=1', {
        method: 'POST',
        credentials: 'include'
      });
      if (!resp.ok) {
        const msg = (await resp.json().catch(() => ({})))?.message || ('HTTP ' + resp.status);
        throw new Error(msg);
      }
      window.location.replace('/index'); // or '/'
    } catch (e) {
      console.warn('Scan failed:', e);
    } finally {
      window.occt?.loading?.hide?.();
      updateScanControls();
    }
  }

  function openDashboardIfAvailable() {
    if (!hasLastScan) { alert('No previous scan found. Start a new scan first.'); return; }
    window.location.replace('/index');
  }

  // ⬇️ NEW: ensure state is correct immediately on page load
  updateScanControls();

  // ⬇️ NEW: react if MODE changes in another tab or page (Settings)
  window.addEventListener('storage', (e) => {
    if (e.key === K.MODE) updateScanControls();
  });

  // Feature fades (unchanged)
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
    });
  }, { threshold: 0.15 });
  document.querySelectorAll('.feature').forEach(el => observer.observe(el));

  viewBtn?.addEventListener('click', openDashboardIfAvailable);
  newBtn?.addEventListener('click', startNewScan);

  loadLastScan();
})();
