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

  const DEFAULTS = { [K.THEME]: 'light', [K.MODE]: 'live' };

  const setText = (el, v) => { if (el) el.textContent = v; };
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.hidden = true), 1400);
  }

  function pickDurationMs(obj) {
    if (!obj || typeof obj !== 'object') return null;
    const n = (v) => Number.isFinite(v) ? v : null;
    const parseTs = (v) => v ? Date.parse(v) : NaN;
    const dm = n(obj.duration_ms);
    if (dm != null) return dm;
    const em = n(obj.elapsed_ms);
    if (em != null) return em;
    const a = parseTs(obj.started_at || obj.start_time || obj.started);
    const b = parseTs(obj.completed_at || obj.end_time || obj.finished);
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) return b - a;
    return null;
  }

  function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '—';
    if (ms < 90000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return s ? `${m}m ${s}s` : `${m}m`;
  }

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
      const r = await fetch(pageApi('/last-scan'), { headers: { 'X-OCCT-No-Loader': '1' }, cache: 'no-store' });
      const j = await r.json();
      setText(textEl, 'Last scan: ' + (j?.has_data ? fmt(j.completed_at) : '—'));
      hint.hidden = false;
    } catch {}
  }

  function load() {
    const theme = (localStorage.getItem(K.THEME) || DEFAULTS[K.THEME]);
    const mode  = (localStorage.getItem(K.MODe || K.MODE)  || DEFAULTS[K.MODE]);
    if (themeDark) themeDark.checked = (theme === 'dark');
    if (apiMode)   apiMode.value     = mode;
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    updateRescanState();
    refreshHeaderLastScan();
    refreshScanAvailability();
  }

  function applyThemeFromToggle() {
    const dark = !!themeDark?.checked;
    try { localStorage.setItem(K.THEME, dark ? 'dark' : 'light'); } catch {}
    document.documentElement.classList.toggle('theme-dark', dark);
    showToast(`Theme: ${dark ? 'Dark' : 'Light'}`);
  }

  function updateRescanState() {
    if (!rescanBtn) return;
    const isSample = getModeLocal() === 'sample';
    rescanBtn.disabled = isSample;
    rescanBtn.setAttribute('aria-disabled', String(isSample));
    rescanBtn.title = isSample ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.' : '';
    rescanBtn.classList.toggle('is-disabled', isSample);
    if (rescanHint) {
      rescanHint.hidden = !isSample;
      rescanHint.textContent = isSample ? 'Disabled in SAMPLE mode. Switch to LIVE to run a scan.' : '';
    }
  }

  async function pullLiveJobTotals(baseRescanUrl, jobId) {
    try {
      const jobsBase = baseRescanUrl.replace(/\/rescan(\?.*)?$/, '/jobs/');
      const url = `${jobsBase}${jobId}?verbose=1`;
      const jr = await fetch(url, { headers: { 'X-OCCT-No-Loader': '1' }, cache: 'no-store' });
      const j = await jr.json().catch(() => ({}));
      const num = (v) => (v == null ? null : Number(v));
      return {
        ing:  num(j?.inserted_total ?? j?.ingested ?? null),
        fail: num(j?.failed_count  ?? j?.failed    ?? null),
        dur:  pickDurationMs(j)
      };
    } catch {
      return { ing: null, fail: null, dur: null };
    }
  }

  async function autoRescanLive() {
    const started = (performance && performance.now) ? performance.now() : Date.now();
    try {
      if (window.occt?.loading?.show) window.occt.loading.show();
      const rescanUrl = '/api/live/rescan?wait=1';
      const resp = await fetch(rescanUrl, { method: 'POST' });
      const body = await resp.json().catch(() => ({}));
      let durMs = pickDurationMs(body) ?? ((performance && performance.now) ? (performance.now() - started) : (Date.now() - started));
      const toNum = (v) => (v == null ? null : Number(v));
      let ing  = toNum(body?.ingested ?? body?.inserted_total ?? null);
      let fail = toNum(body?.failed   ?? body?.failed_count   ?? null);
      if (body?.job_id) {
        const j = await pullLiveJobTotals('/api/live/rescan', body.job_id);
        if (j.ing  != null) ing  = j.ing;
        if (j.fail != null) fail = j.fail;
        if (j.dur  != null) durMs = j.dur;
      }
      if (resp.ok) {
        setText(rescanMsg, 'Scan complete.');
        showToast(`Scan complete, duration: ${formatDuration(durMs)}`);
        await refreshHeaderLastScan();
        await refreshScanAvailability();
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
    refreshHeaderLastScan();
    refreshScanAvailability();
    if (mode === 'live') {
      autoRescanLive();
    } else {
      setText(rescanMsg, '');
    }
  }

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
    refreshScanAvailability();
    showToast('Defaults restored');
    if (prevMode !== 'live' && DEFAULTS[K.MODE] === 'live') {
      autoRescanLive();
    } else {
      setText(rescanMsg, '');
    }
  }

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
    const started = (performance && performance.now) ? performance.now() : Date.now();
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
      const toNum = (v) => (v == null ? null : Number(v));
      let ing  = toNum(body?.ingested ?? body?.inserted_total ?? null);
      let fail = toNum(body?.failed   ?? body?.failed_count   ?? null);
      let durMs = pickDurationMs(body);
      const isLive = baseUrl.startsWith('/api/live');
      if (body?.job_id && isLive) {
        const j = await pullLiveJobTotals(baseUrl, body.job_id);
        if (j.ing  != null) ing  = j.ing;
        if (j.fail != null) fail = j.fail;
        if (j.dur  != null) durMs = j.dur;
      }
      if (!Number.isFinite(durMs)) {
        durMs = (performance && performance.now) ? (performance.now() - started) : (Date.now() - started);
      }
      setText(rescanMsg, 'Scan complete.');
      showToast(`Scan complete, duration: ${formatDuration(durMs)}`);
      await refreshHeaderLastScan();
      await refreshScanAvailability();
    } catch (e) {
      const msg = `Rescan error: ${e}`;
      showToast('Rescan error'); setText(rescanMsg, msg);
    } finally {
      rescanBtn.textContent = orig;
      updateRescanState();
    }
  }

  function blockNav(e) { e.preventDefault(); e.stopPropagation(); }
  function blockKey(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); }
  }

  function setScanControlsEnabled(enabled, meta, mode) {
    const ctrls = document.querySelectorAll('[data-live-only]');
    ctrls.forEach(el => {
      const tag = el.tagName.toUpperCase();
      const offTitle = `No ${mode.toUpperCase()} scans yet`;
      if (tag === 'A') {
        if (enabled) {
          if (el.dataset.hrefBackup) {
            el.setAttribute('href', el.dataset.hrefBackup);
            delete el.dataset.hrefBackup;
          }
          el.classList.remove('is-disabled');
          el.removeAttribute('aria-disabled');
          el.removeAttribute('tabindex');
          el.removeEventListener('click', blockNav);
          el.removeEventListener('keydown', blockKey);
          el.removeAttribute('title');
        } else {
          if (!el.dataset.hrefBackup) {
            el.dataset.hrefBackup = el.getAttribute('href') || '';
          }
          el.setAttribute('href', '#');
          el.classList.add('is-disabled');
          el.setAttribute('aria-disabled', 'true');
          el.setAttribute('tabindex', '-1');
          el.addEventListener('click', blockNav);
          el.addEventListener('keydown', blockKey);
          el.title = offTitle;
        }
        return;
      }
      el.disabled = !enabled;
      el.setAttribute('aria-disabled', String(!enabled));
      el.classList.toggle('is-disabled', !enabled);
      if (!enabled) {
        el.title = offTitle;
        el.tabIndex = -1;
      } else {
        el.removeAttribute('title');
        el.removeAttribute('tabindex');
      }
    });
    const groups = document.querySelectorAll('[data-live-section]');
    groups.forEach(group => {
      const isFieldset = group.tagName && group.tagName.toUpperCase() === 'FIELDSET';
      if (isFieldset) group.disabled = !enabled;
      group.classList.toggle('is-disabled', !enabled);
      group.setAttribute('aria-disabled', String(!enabled));
    });
    const banner = document.getElementById('settings-live-banner');
    if (banner) banner.classList.toggle('hidden', !!enabled);
  }

  async function refreshScanAvailability() {
    const mode = getModeLocal();
    try {
      const r = await fetch(pageApi('/last-scan'), {
        cache: 'no-store',
        headers: { 'X-OCCT-No-Loader': '1' }
      });
      if (!r.ok) throw new Error('status ' + r.status);
      const j = await r.json();
      const hasScan = !!j?.has_data;
      setScanControlsEnabled(hasScan, { last_time: j?.completed_at }, mode);
    } catch {
      setScanControlsEnabled(false, null, mode);
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
  function logoutNow() {
    window.location.replace('/logout');
  }

  window.addEventListener('storage', (e) => {
    if (e.key === K.MODE) {
      updateRescanState();
      refreshHeaderLastScan();
      refreshScanAvailability();
    }
    if (e.key === K.THEME) {
      const dark = (e.newValue || 'light') === 'dark';
      if (themeDark) themeDark.checked = dark;
      document.documentElement.classList.toggle('theme-dark', dark);
    }
  });

  themeDark?.addEventListener('change', applyThemeFromToggle);
  apiMode?.addEventListener('change', onModeChange);
  resetBtn?.addEventListener('click', resetAll);
  logoutBtn?.addEventListener('click', logoutNow);
  rescanBtn?.addEventListener('click', doRescan);
  reportBtn?.addEventListener('click', openReport);
  reportDlBtn?.addEventListener('click', downloadReport);

  load();
})();
