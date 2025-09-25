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

  // Auto-rescan helper when switching to LIVE (shows loading overlay if available)
  async function autoRescanLive() {
    try {
      if (window.occt && window.occt.loading && window.occt.loading.show) {
        window.occt.loading.show();
      }
      const resp = await fetch('/api/live/rescan?wait=1', {
        method: 'POST'
        // No 'X-OCCT-No-Loader' header here — we WANT the page overlay for mode switch
      });
      const body = await resp.json().catch(() => ({}));

      // Build friendly message if we have counts
      const numberOrDash = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : '—');
      const ing  = body?.ingested ?? body?.inserted_total;
      const tot  = body?.total_unique ?? body?.unique ?? body?.total;
      const fail = body?.failed_unique ?? body?.failed ?? body?.failed_count;

      if (resp.ok) {
        setText(rescanMsg, `Rescan OK. Ingested: ${numberOrDash(ing)}, Total unique: ${numberOrDash(tot)}, Failed: ${numberOrDash(fail)}`);
        showToast('LIVE rescan complete');
      } else {
        const msg = body?.message || `LIVE rescan failed (${resp.status})`;
        setText(rescanMsg, msg);
        showToast(msg);
      }
    } catch (e) {
      setText(rescanMsg, `LIVE rescan error: ${e}`);
      showToast('LIVE rescan error');
    } finally {
      if (window.occt && window.occt.loading && window.occt.loading.hide) {
        window.occt.loading.hide();
      }
    }
  }

  function onModeChange() {
    const mode = apiMode?.value === 'live' ? 'live' : 'sample';
    localStorage.setItem(K.MODE, mode);
    showToast(`Data source: ${mode.toUpperCase()}`);
    // Trigger auto-rescan when switching to LIVE
    if (mode === 'live') {
      autoRescanLive();
    }
  }

  function resetAll() {
    Object.entries(DEFAULTS).forEach(([k, v]) => localStorage.setItem(k, v));
    load();
    showToast('Defaults restored');
  }

  // Updated doRescan (manual button) with wait=1 and header to avoid double spinner
  async function doRescan() {
    if (!rescanBtn) return;
    rescanBtn.disabled = true;
    const orig = rescanBtn.textContent;
    rescanBtn.textContent = 'Rescanning…';
    setText(rescanMsg, '');

    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    const numberOrDash = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : '—');

    try {
      // Build URL (LIVE/SAMPLE aware)
      const baseUrl = (window.occt && window.occt.api) ? window.occt.api('/rescan') : '/api/sample/rescan';
      const urlWithWait = baseUrl + (baseUrl.includes('?') ? '&' : '?') + 'wait=1';

      // Post and opt-out of the global overlay (button already shows state)
      const resp = await fetch(urlWithWait, {
        method: 'POST',
        headers: { 'X-OCCT-No-Loader': '1' }  // avoid double spinners
      });

      const body = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        const msg = body?.message || `Rescan failed (${resp.status})`;
        showToast(msg); setText(rescanMsg, msg);
        return;
      }

      // Read counts if provided immediately
      let ing  = body?.ingested ?? body?.inserted_total ?? null;
      let tot  = body?.total_unique ?? body?.unique ?? body?.total ?? null;
      let fail = body?.failed_unique ?? body?.failed ?? body?.failed_count ?? null;

      // If backend only returned job_id (queued) and we’re in LIVE, poll jobs/<id>
      const isLive = baseUrl.startsWith('/api/live');
      if ((ing == null && tot == null && fail == null) && body?.job_id && isLive) {
        const jobsBase = baseUrl.replace(/\/rescan(\?.*)?$/, '/jobs/');
        const jobUrl = jobsBase + body.job_id + '?verbose=1';
        const deadline = Date.now() + 20000; // ~20s

        let job = null;
        do {
          await sleep(600);
          const jr = await fetch(jobUrl, { headers: { 'X-OCCT-No-Loader': '1' } });
          job = await jr.json().catch(() => ({}));
        } while (job && job.status && job.status !== 'done' && job.status !== 'error' && Date.now() < deadline);

        ing  = job?.inserted_total ?? job?.ingested ?? ing;
        tot  = job?.total_unique ?? job?.unique ?? job?.total ?? tot;
        fail = job?.failed_unique ?? job?.failed ?? job?.failed_count ?? fail;

        const statusText = job?.status === 'done' ? 'OK' : (job?.status || 'complete');
        setText(rescanMsg, `Rescan ${statusText}. Ingested: ${numberOrDash(ing)}, ` +
                           `Total unique: ${numberOrDash(tot)}, Failed: ${numberOrDash(fail)}`);
        showToast(job?.status === 'done' ? 'Rescan complete' : 'Rescan finished with issues');
        return;
      }

      // Success with counts
      setText(rescanMsg, `Rescan OK. Ingested: ${numberOrDash(ing)}, ` +
                         `Total unique: ${numberOrDash(tot)}, Failed: ${numberOrDash(fail)}`);
      showToast('Rescan complete');

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
