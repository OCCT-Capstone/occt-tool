// frontend/js/home.js
(function () {
  const occt = window.occt || { K: { MODE: 'occt.apiMode' } };
  const K = occt.K;
  const $ = (s, r = document) => r.querySelector(s);

  // Buttons present on Home
  const viewBtn = $('#viewLastBtn');
  const newBtn  = $('#newScanBtn');

  // Optional (only paint if these exist)
  const eventsEl = $('#lastScanEvents');
  const failEl   = $('#lastScanFailed');

  // --- Mode helpers ---
  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch { return 'live'; }
  }
  (function setDefaultModeOnce(){
    try { if (!localStorage.getItem(K.MODE)) localStorage.setItem(K.MODE, 'live'); } catch {}
  })();

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

  // Background paint of lightweight stats (optional only)
  async function loadLastScan() {
    try {
      updateScanControls();
      const res = await fetch(pageApi('/last-scan'), {
        // IMPORTANT: do NOT add the X-OCCT-No-Loader header here if you want loader.
        // We keep it loader-free for this background pull only:
        headers: { 'X-OCCT-No-Loader': '1' },
        credentials: 'include'
      });
      if (!res.ok) return;
      const j = await res.json();
      const has = !!j?.has_data;

      if (viewBtn) {
        // You said both buttons should go to Dashboard anyway, so we leave it enabled;
        // if you want to disable when empty, uncomment below:
        // has ? viewBtn.removeAttribute('disabled') : viewBtn.setAttribute('disabled','true');
        viewBtn.removeAttribute('disabled');
      }
      if (has) {
        if (eventsEl && typeof j.event_count !== 'undefined') eventsEl.textContent = j.event_count;
        if (failEl && typeof j.failed_count  !== 'undefined') failEl.textContent  = j.failed_count;
      } else {
        if (eventsEl) eventsEl.textContent = '—';
        if (failEl)   failEl.textContent   = '—';
      }
    } catch {
      /* silent */
    }
  }

  // Start new scan (LIVE only) → show loader (via global fetch hook) → go to Dashboard
    async function startNewScan() {
    if (getMode() === 'sample') return;
    if (newBtn) newBtn.disabled = true;

    // Explicitly show loader immediately (in addition to loader.js’ fetch wrapper)
    window.occt?.loading?.show?.();

    try {
        const resp = await fetch(pageApi('/rescan') + '?wait=1', {
        method: 'POST',
        credentials: 'include'
        // NOTE: no 'X-OCCT-No-Loader' — let loader.js auto-show too
        });
        if (!resp.ok) {
        const msg = (await resp.json().catch(() => ({})))?.message || ('HTTP ' + resp.status);
        throw new Error(msg);
        }
        window.location.replace('/index'); // change to '/' if your dashboard is root
    } catch (e) {
        console.warn('Scan failed:', e);
        // Optional: toast here if you want visible feedback
    } finally {
        // Hide our explicit overlay (loader.js will also hide once inflight=0)
        window.occt?.loading?.hide?.();
        updateScanControls();
    }
    }


  // View last → just go to Dashboard
  function goDashboard() {
    window.location.replace('/index'); // change to '/' if needed
  }

  // Scroll animation for features
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
        }
        });
    }, { threshold: 0.15 });

    document.querySelectorAll('.feature').forEach(el => observer.observe(el));

  // Wire
  viewBtn?.addEventListener('click', goDashboard);
  newBtn?.addEventListener('click', startNewScan);

  // Init
  loadLastScan();
})();