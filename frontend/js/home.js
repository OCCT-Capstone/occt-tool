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

  // --- helpers for disabling anchors/buttons ---
  function blockNav(e) { e.preventDefault(); e.stopPropagation(); }
  function blockKey(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault(); e.stopPropagation();
    }
  }

  // Mode-aware gating: elements marked data-live-only actually mean "requires last scan in current mode"
  function setRequiresScanButtonsEnabled(enabled, meta, mode) {
    const btns = document.querySelectorAll('[data-live-only].btn, button[data-live-only]');
    btns.forEach(btn => {
      btn.disabled = !enabled;
      btn.setAttribute('aria-disabled', String(!enabled));
      btn.classList.toggle('is-disabled', !enabled);
      if (!enabled) {
        btn.title = `No ${mode.toUpperCase()} scans yet`;
        btn.tabIndex = -1;
      } else {
        btn.removeAttribute('title');
        btn.removeAttribute('tabindex');
      }
    });

    // Optional: show last time somewhere if you have #live-last-time
    if (enabled && meta?.last_time) {
      const el = document.querySelector('#live-last-time');
      if (el) el.textContent = new Date(meta.last_time).toLocaleString();
    }
  }

  function setRequiresScanLinksEnabled(enabled, mode) {
    const links = document.querySelectorAll('a[data-live-only]');
    links.forEach(a => {
      if (enabled) {
        if (a.dataset.hrefBackup) {
          a.setAttribute('href', a.dataset.hrefBackup);
          delete a.dataset.hrefBackup;
        }
        a.classList.remove('is-disabled');
        a.removeAttribute('aria-disabled');
        a.removeAttribute('tabindex');
        a.removeEventListener('click', blockNav);
        a.removeEventListener('keydown', blockKey);
        a.removeAttribute('title');
      } else {
        if (!a.dataset.hrefBackup) {
          a.dataset.hrefBackup = a.getAttribute('href') || '';
        }
        a.setAttribute('href', '#');
        a.classList.add('is-disabled');
        a.setAttribute('aria-disabled', 'true');
        a.setAttribute('tabindex', '-1');
        a.addEventListener('click', blockNav);
        a.addEventListener('keydown', blockKey);
        a.title = `No ${mode.toUpperCase()} scans yet`;
      }
    });
  }

  // --- mode + API helpers ---
  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch { return 'live'; }
  }
  try { if (!localStorage.getItem(K.MODE)) localStorage.setItem(K.MODE, 'live'); } catch {}

  function pageApi(path) {
    return (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;
  }

  // --- UI state for "New Scan" in SAMPLE vs LIVE ---
  function updateScanControls() {
    const isSample = getMode() === 'sample';
    if (newBtn) {
      newBtn.disabled = isSample;
      newBtn.title = isSample ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.' : '';
      newBtn.classList.toggle('is-disabled', isSample);
    }
  }

  // --- fetch last-scan meta for CURRENT mode and gate UI accordingly ---
  async function loadLastScan() {
    try {
      updateScanControls();
      const mode = getMode(); // 'live' or 'sample'
      const res = await fetch(pageApi('/last-scan'), {
        headers: { 'X-OCCT-No-Loader': '1' },
        credentials: 'include',
        cache: 'no-store'
      });
      if (!res.ok) {
        // Safe default: treat as no scan
        hasLastScan = false;
      } else {
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

        // Mode-aware gating for nav/buttons that require a last scan
        setRequiresScanButtonsEnabled(hasLastScan, { last_time: j?.completed_at }, mode);
        setRequiresScanLinksEnabled(hasLastScan, mode);
      }
    } catch {
      hasLastScan = false;
      setRequiresScanButtonsEnabled(false, null, getMode());
      setRequiresScanLinksEnabled(false, getMode());
    }
  }

  // --- actions ---
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

  // Ensure correct state on load
  updateScanControls();

  // React if MODE changes in another tab or page (Settings)
  window.addEventListener('storage', (e) => {
    if (e.key === K.MODE) {
      updateScanControls();
      loadLastScan(); // refresh counts + gating for the new mode
    }
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

  // Kick off
  loadLastScan();
})();
