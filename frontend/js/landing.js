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

  const dataEl   = $('#lastScanData');
  const hintEl   = $('#lastScanHint');

  const viewBtn  = $('#viewLastBtn');
  const newBtn   = $('#newScanBtn');

  const themeToggle  = $('#themeToggle');
  const sampleToggle = $('#sampleToggle');
  const logoutBtn    = $('#logoutBtn');

  // Resolve mode from localStorage (project does not use cookies for mode)
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

  function setHint(text) {
    if (!hintEl) return;
    hintEl.textContent = text || '';
  }

  function buildUnifiedHint({ hasData }) {
    const isSample = getMode() === 'sample';
    const parts = [];

    if (!hasData) parts.push('No scan found yet.');
    if (isSample) parts.push('Start new scan is disabled in SAMPLE mode. Switch to LIVE to run a scan.');
    return parts.join(' ');
  }

  function updateScanControls() {
    const isSample = getMode() === 'sample';
    if (newBtn) {
      newBtn.disabled = isSample;
      newBtn.title = isSample
        ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.'
        : '';
      newBtn.classList.toggle('is-disabled', isSample);
    }
  }

  async function loadLastScan() {
    try {
      updateScanControls();

      const res = await fetch(pageApi('/last-scan'), { headers:{ 'X-OCCT-No-Loader':'1' } });
      const j = await res.json();

      if (!j?.has_data) {
        // Hide stats, show unified hint
        if (dataEl) dataEl.hidden = true;
        setHint(buildUnifiedHint({ hasData:false }));
        if (viewBtn) viewBtn.setAttribute('disabled', 'true');
        return false;
      }

      // Show stats
      if (dataEl) dataEl.hidden = false;
      if (viewBtn) viewBtn.removeAttribute('disabled');

      timeEl.textContent   = fmt(j.completed_at);
      hostsEl.textContent  = j.host_count ?? '—';
      eventsEl.textContent = j.event_count ?? '—';
      failEl.textContent   = j.failed_count ?? '—';

      // Even with data, still show sample-mode notice if applicable
      setHint(buildUnifiedHint({ hasData:true }));

      const changed = j.completed_at !== lastCompleted;
      lastCompleted = j.completed_at;
      return changed;

    } catch (e) {
      setHint('Failed to load last scan.');
      return false;
    }
  }

  async function startNewScan() {
    setHint('Scanning…');
    newBtn.setAttribute('disabled', 'true');
    try {
      const resp = await fetch(pageApi('/rescan') + '?wait=1', { method:'POST' });
      if (!resp.ok) {
        const msg = (await resp.json().catch(()=>({})))?.message || ('HTTP ' + resp.status);
        throw new Error(msg);
      }
      // Go to Dashboard to view fresh data
      window.location.replace('/');
    } catch (e) {
      setHint('Scan failed: ' + e.message);
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
    // Update unified hint to reflect new mode
    setHint(buildUnifiedHint({ hasData: !(dataEl?.hidden) }));
    await loadLastScan();
  });

  logoutBtn?.addEventListener('click', () => window.location.replace('/logout'));

  viewBtn?.addEventListener('click', openDashboard);
  newBtn?.addEventListener('click', startNewScan);

  hydrateToggles();
  loadLastScan();
})();
