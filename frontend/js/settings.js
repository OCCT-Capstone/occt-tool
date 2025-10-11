// static/js/settings.js
(function () {
  const occt = window.occt || { K: { THEME: 'occt.theme', MODE: 'occt.apiMode' } };
  const K = occt.K;

  const $ = (s) => document.querySelector(s);
  const themeDark   = $('#themeDark');
  const apiMode     = $('#apiMode');
  const toast       = $('#toast');
  const resetBtn    = $('#resetBtn');
  const logoutBtn   = $('#logoutBtn');
  const rescanBtn   = $('#rescanBtn');
  const rescanMsg   = $('#rescanStatus');
  const rescanHint  = $('#rescanHint');
  const reportBtn   = $('#reportBtn');
  const reportDlBtn = $('#reportDlBtn');

  // Defaults: Light + LIVE
  const DEFAULTS = { [K.THEME]: 'light', [K.MODE]: 'live' };

  const setText = (el, v) => { if (el) el.textContent = v; };
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.hidden = true), 1400);
  }

  /* ---------------- duration helpers ---------------- */

  function pickDurationMs(obj) {
    if (!obj || typeof obj !== 'object') return null;
    const n = (v) => Number.isFinite(v) ? v : null;
    const parseTs = (v) => v ? Date.parse(v) : NaN;

    // direct numeric fields first
    const dm = n(obj.duration_ms);
    if (dm != null) return dm;
    const em = n(obj.elapsed_ms);
    if (em != null) return em;

    // derive from timestamps if available
    const a = parseTs(obj.started_at || obj.start_time || obj.started);
    const b = parseTs(obj.completed_at || obj.end_time || obj.finished);
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) return b - a;

    return null;
  }

  function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '—';
    if (ms < 90_000) {
      return `${(ms / 1000).toFixed(1)}s`;
    }
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return s ? `${m}m ${s}s` : `${m}m`;
  }

  /* ---------------- API + header hint helpers ---------------- */

  function getModeLocal() {
    const v = apiMode?.value;
    if (v === 'live' || v === 'sample') return v;
    try { return localStorage.getItem(K.MODE) || DEFAULTS[K.MODE]; } catch { return DEFAULTS[K.MODE]; }
  }
  function pageApi(path) {
    return (getModeLocal() === 'sample' ? '/api/sample' : '/api/live') + path;
  }
  function fmt(iso) {
    if (!iso) return '—';
    try { return (window.occt?.formatDateTimeAU ? window.occt.formatDateTimeAU(iso) : iso); }
    catch { return iso; }
  }
  async function refreshHeaderLastScan() {
    const hint = document.getElementById('lastScanHeaderHint');
    if (!hint) return;
    const textEl = hint.querySelector('.text') || hint;
    try {
      const r = await fetch(pageApi('/last-scan'), { headers: { 'X-OCCT-No-Loader': '1' } });
      const j = await r.json();
      setText(textEl, 'Last scan: ' + (j?.has_data ? fmt(j.completed_at) : '—'));
      hint.hidden = false;
    } catch { /* leave whatever is there */ }
  }

  /* ---------------- load + theme ---------------- */

  function load() {
    const theme = (localStorage.getItem(K.THEME) || DEFAULTS[K.THEME]);
    const mode  = (localStorage.getItem(K.MODE)  || DEFAULTS[K.MODE]);
    if (themeDark) themeDark.checked = (theme === 'dark');
    if (apiMode)   apiMode.value     = mode;
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    updateRescanState();
    refreshHeaderLastScan();
  }

  function applyThemeFromToggle() {
    const dark = !!themeDark?.checked;
    localStorage.setItem(K.THEME, dark ? 'dark' : 'light');
    document.documentElement.classList.toggle('theme-dark', dark);
    showToast(`Theme: ${dark ? 'Dark' : 'Light'}`);
  }

  /* ---------------- rescan button state ---------------- */

  function updateRescanState() {
    if (!rescanBtn) return;
    const isSample = getModeLocal() === 'sample';

    rescanBtn.disabled = isSample;
    rescanBtn.setAttribute('aria-disabled', String(isSample));
    rescanBtn.title = isSample
      ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.'
      : '';
    rescanBtn.classList.toggle('is-disabled', isSample);

    if (rescanHint) {
      rescanHint.hidden = !isSample;
      rescanHint.textContent = isSample
        ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.'
        : '';
    }
  }

  /* ---------------- auto-rescan on switch to LIVE ---------------- */

  async function autoRescanLive() {
    const t0 = (performance && performance.now) ? performance.now() : Date.now();
    try {
      if (window.occt?.loading?.show) window.occt.loading.show();

      const resp = await fetch('/api/live/rescan?wait=1', { method: 'POST' });
      const body = await resp.json().catch(() => ({}));

      // durations: prefer server, else client stopwatch
      const durMs = pickDurationMs(body) ?? ((performance && performance.now) ? (performance.now() - t0) : (Date.now() - t0));

      const numberOrDash = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : '—');
      const ing  = body?.ingested ?? body?.inserted_total;
      const fail = body?.failed_unique ?? body?.failed ?? body?.failed_count;

      if (resp.ok) {
        setText(rescanMsg, `Rescan OK. Ingested: ${numberOrDash(ing)}, Failed: ${numberOrDash(fail)}, Duration: ${formatDuration(durMs)}`);
        showToast('LIVE rescan complete');
        await refreshHeaderLastScan();                // update header hint
      } else {
        const msg = body?.message || `LIVE rescan failed (${resp.status})`;
        setText(rescanMsg, msg);
        showToast(msg);
      }
    } catch (e) {
      setText(rescanMsg, `LIVE rescan error: ${e}`);
      showToast('LIVE rescan error');
    } finally {
      if (window.occt?.loading?.hide) window.occt.loading.hide();
    }
  }

  function onModeChange() {
    const mode = apiMode?.value === 'live' ? 'live' : 'sample';
    try { localStorage.setItem(K.MODE, mode); } catch {}
    showToast(`Data source: ${mode.toUpperCase()}`);
    updateRescanState();

    if (mode === 'live') {
      autoRescanLive();
    } else {
      setText(rescanMsg, '');
      refreshHeaderLastScan();
    }
  }

  /* ---------------- Reset (LIVE default) ---------------- */

  function resetAll() {
    const prevMode = getModeLocal();

    Object.entries(DEFAULTS).forEach(([k, v]) => {
      try { localStorage.setItem(k, v); } catch {}
    });

    if (themeDark) themeDark.checked = (DEFAULTS[K.THEME] === 'dark');
    if (apiMode)   apiMode.value     = DEFAULTS[K.MODE];
    document.documentElement.classList.toggle('theme-dark', DEFAULTS[K.THEME] === 'dark');

    updateRescanState();
    refreshHeaderLastScan();

    showToast('Defaults restored');

    if (prevMode !== 'live' && DEFAULTS[K.MODE] === 'live') {
      autoRescanLive();
    } else {
      setText(rescanMsg, '');
    }
  }

  /* ---------------- manual rescan button ---------------- */

  async function doRescan() {
    if (getModeLocal() === 'sample') {
      showToast('Rescan disabled in SAMPLE mode');
      setText(rescanMsg, 'Rescan disabled in SAMPLE mode');
      return;
    }

    if (!rescanBtn) return;
    rescanBtn.disabled = true;
    const orig = rescanBtn.textContent;
    rescanBtn.textContent = 'Rescanning…';
    setText(rescanMsg, '');

    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    const numberOrDash = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : '—');
    const t0 = (performance && performance.now) ? performance.now() : Date.now();

    try {
      const baseUrl = (window.occt && window.occt.api) ? window.occt.api('/rescan') : '/api/live/rescan';
      const urlWithWait = baseUrl + (baseUrl.includes('?') ? '&' : '?') + 'wait=1';

      const resp = await fetch(urlWithWait, {
        method: 'POST',
        headers: { 'X-OCCT-No-Loader': '1' }
      });

      const body = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        const msg = body?.message || `Rescan failed (${resp.status})`;
        showToast(msg); setText(rescanMsg, msg);
        return;
      }

      let ing  = body?.ingested ?? body?.inserted_total ?? null;
      let tot  = body?.total_unique ?? body?.unique ?? body?.total ?? null; // not displayed anymore, but used as a signal during polling
      let fail = body?.failed_unique ?? body?.failed ?? body?.failed_count ?? null;
      let durMs = pickDurationMs(body); // may be null

      const isLive = baseUrl.startsWith('/api/live');
      if ((ing == null && tot == null && fail == null) && body?.job_id && isLive) {
        const jobsBase = baseUrl.replace(/\/rescan(\?.*)?$/, '/jobs/');
        const jobUrl = jobsBase + body.job_id + '?verbose=1';
        const deadline = Date.now() + 20000;
        let job = null;

        do {
          await sleep(600);
          const jr = await fetch(jobUrl, { headers: { 'X-OCCT-No-Loader': '1' } });
          job = await jr.json().catch(() => ({}));
        } while (job && job.status && job.status !== 'done' && job.status !== 'error' && Date.now() < deadline);

        ing  = job?.inserted_total ?? job?.ingested ?? ing;
        tot  = job?.total_unique   ?? job?.unique   ?? job?.total ?? tot;
        fail = job?.failed_unique  ?? job?.failed   ?? job?.failed_count ?? fail;
        durMs = pickDurationMs(job) ?? durMs;
      }

      // fall back to client stopwatch if server didn't supply duration
      if (!Number.isFinite(durMs)) {
        durMs = (performance && performance.now) ? (performance.now() - t0) : (Date.now() - t0);
      }

      setText(rescanMsg, `Rescan OK. Ingested: ${numberOrDash(ing)}, Failed: ${numberOrDash(fail)}, Duration: ${formatDuration(durMs)}`);
      showToast('Rescan complete');
      await refreshHeaderLastScan();

    } catch (e) {
      const msg = `Rescan error: ${e}`;
      showToast('Rescan error'); setText(rescanMsg, msg);
    } finally {
      rescanBtn.textContent = orig;
      updateRescanState();
    }
  }

  /* ---------------- report + logout ---------------- */

  function openReport() {
    const url = (window.occt && window.occt.api) ? window.occt.api('/report') : '/api/sample/report';
    window.open(url, '_blank');
  }
  function downloadReport() {
    const base = (window.occt && window.occt.api) ? window.occt.api('/report') : '/api/sample/report';
    window.location.href = `${base}?download=1`;
  }
  function logoutNow() {
    window.location.replace('/logout');
  }

  /* ---------------- cross-tab sync ---------------- */

  window.addEventListener('storage', (e) => {
    if (e.key === K.MODE) { updateRescanState(); refreshHeaderLastScan(); }
    if (e.key === K.THEME) {
      const dark = (e.newValue || 'light') === 'dark';
      if (themeDark) themeDark.checked = dark;
      document.documentElement.classList.toggle('theme-dark', dark);
    }
  });

  /* ---------------- wire events ---------------- */

  themeDark?.addEventListener('change', applyThemeFromToggle);
  apiMode?.addEventListener('change', onModeChange);
  resetBtn?.addEventListener('click', resetAll);
  logoutBtn?.addEventListener('click', logoutNow);
  rescanBtn?.addEventListener('click', doRescan);
  reportBtn?.addEventListener('click', openReport);
  reportDlBtn?.addEventListener('click', downloadReport);

  load();
})();
