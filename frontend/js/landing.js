// frontend/js/landing.js
(function () {
  const occt = window.occt || { K:{ THEME:'occt.theme', MODE:'occt.apiMode' } };
  const K = occt.K;
  const $ = (s) => document.querySelector(s);

  // Elements
  const timeEl   = $('#lastScanTime');
  const hostsEl  = $('#lastScanHosts');
  const eventsEl = $('#lastScanEvents');
  const failEl   = $('#lastScanFailed');
  const emptyEl  = $('#lastScanEmpty');
  const dataEl   = $('#lastScanData');
  const statusEl = $('#scanStatus');
  const viewBtn  = $('#viewLastBtn');
  const newBtn   = $('#newScanBtn');

  const themeToggle  = $('#themeToggle');
  const sampleToggle = $('#sampleToggle');
  const logoutBtn    = $('#logoutBtn');

  // Resolve mode fresh from localStorage (project does not use cookies for mode)
  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch (_) { return 'live'; }
  }
  function pageApi(path) {
    return (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;
  }

  // Default to LIVE once for admins if unset
  try { if (!localStorage.getItem(K.MODE)) localStorage.setItem(K.MODE, 'live'); } catch(_){}

  const fmt = (occt.formatDateTimeAU || ((iso)=>iso||''));
  let lastCompleted = null;

  function updateScanControls() {
    const isSample = getMode() === 'sample';
    if (newBtn) {
      newBtn.disabled = isSample;
      newBtn.classList.toggle('is-disabled', isSample); // greys out & shows ⛔ if CSS added
      newBtn.setAttribute('aria-disabled', String(isSample));
      newBtn.title = isSample
        ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.'
        : '';
    }
    if (statusEl) {
      statusEl.textContent = isSample ? 'Start new scan is disabled. Switch to LIVE to run a scan.' : '';
    }
  }

  async function loadLastScan() {
    try {
      updateScanControls();
      const res = await fetch(pageApi('/last-scan'), { headers:{ 'X-OCCT-No-Loader':'1' } });
      const j = await res.json();
      if (!j?.has_data) {
        emptyEl.hidden = false; dataEl.hidden = true;
        viewBtn?.setAttribute('disabled', 'true');
        return false;
      }
      emptyEl.hidden = true; dataEl.hidden = false;
      timeEl.textContent   = fmt(j.completed_at);
      hostsEl.textContent  = j.host_count ?? '—';
      eventsEl.textContent = j.event_count ?? '—';
      failEl.textContent   = j.failed_count ?? '—';
      viewBtn?.removeAttribute('disabled');
      const changed = j.completed_at !== lastCompleted;
      lastCompleted = j.completed_at;
      return changed;
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Failed to load last scan';
      return false;
    }
  }

  async function startNewScan() {
    // Guard: do nothing in SAMPLE mode
    if (getMode() === 'sample') {
      if (statusEl) statusEl.textContent = 'Start new scan is disabled. Switch to LIVE to run a scan.';
      return;
    }

    if (statusEl) statusEl.textContent = 'Scanning...';
    newBtn?.setAttribute('disabled', 'true');

    try {
      // /api/<mode>/rescan?wait=1
      const resp = await fetch(pageApi('/rescan') + '?wait=1', { method:'POST' });
      if (!resp.ok) {
        const msg = (await resp.json().catch(()=>({})))?.message || ('HTTP ' + resp.status);
        throw new Error(msg);
      }
      // Go to Dashboard to view fresh data
      window.location.replace('/');
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Scan failed: ' + e.message;
    } finally {
      updateScanControls(); // restore disabled state based on mode
    }
  }

  function openDashboard() {
    window.location.replace('/');
  }

  // Mini settings
  function hydrateToggles() {
    const dark = (localStorage.getItem(K.THEME) || 'light') === 'dark';
    if (themeToggle) themeToggle.checked = dark;
    document.documentElement.classList.toggle('theme-dark', dark);

    const mode = (localStorage.getItem(K.MODE) || 'live');
    if (sampleToggle) sampleToggle.checked = (mode === 'sample');
    updateScanControls();
  }

  themeToggle?.addEventListener('change', () => {
    const next = themeToggle.checked ? 'dark' : 'light';
    localStorage.setItem(K.THEME, next);
    document.documentElement.classList.toggle('theme-dark', next === 'dark');
  });

  sampleToggle?.addEventListener('change', async () => {
    const next = sampleToggle.checked ? 'sample' : 'live';
    try { localStorage.setItem(K.MODE, next); } catch(_) {}
    updateScanControls();
    await loadLastScan();
  });

  logoutBtn?.addEventListener('click', () => window.location.replace('/logout'));

  viewBtn?.addEventListener('click', openDashboard);
  newBtn?.addEventListener('click', startNewScan);

  hydrateToggles();
  loadLastScan();
})();
