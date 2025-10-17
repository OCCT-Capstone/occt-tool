// frontend/js/detections.js
(function () {
  const occt = window.occt || { K: { MODE: 'occt.apiMode' } };
  const K = occt.K;
  const getMode = () => { try { return localStorage.getItem(K.MODE) || 'live'; } catch { return 'live'; } };
  const api = (path) => (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;

  const $ = (s, r = document) => r.querySelector(s);

  const modeBadge    = $('#modeBadge');
  const noDataBanner = $('#noDataBanner');

  const tabAlerts  = $('#tabAlerts');
  const tabEvents  = $('#tabEvents');
  const alertsPane = $('#alertsPane');
  const eventsPane = $('#eventsPane');

  // filters – alerts
  const fSeverity   = $('#fSeverity');
  const fStatus     = $('#fStatus');
  const fRule       = $('#fRule');
  const fQAlerts    = $('#fQAlerts');
  const btnSearchAl = $('#btnSearchAlerts');
  const btnClearAl  = $('#btnClearAlerts');

  // filters – events
  const fEventId    = $('#fEventId');
  const fAccount    = $('#fAccount');
  const fIp         = $('#fIp');
  const fQEvents    = $('#fQEvents');
  const btnSearchEv = $('#btnSearchEv');
  const btnClearEv  = $('#btnClearEv');

  const alertsTbody = $('#alertsTbody');
  const eventsTbody = $('#eventsTbody');

  let limit = 50;
  let alertsPage = 1, alertsTotal = 0;
  let eventsPage = 1, eventsTotal = 0;
  const alertsPrev = $('#alertsPrev'), alertsNext = $('#alertsNext'), alertsPageEl = $('#alertsPage');
  const eventsPrev = $('#eventsPrev'), eventsNext = $('#eventsNext'), eventsPageEl = $('#eventsPage');

  /* ---------- utils ---------- */
  const fmtTime = (iso) => {
    if (!iso) return '—';
    try { return (window.occt?.formatDateTimeAU ? window.occt.formatDateTimeAU(iso) : new Date(iso).toLocaleString()); }
    catch { return iso; }
  };

  const sevClass = (s) => {
    s = (s || '').toLowerCase();
    return ['critical', 'high', 'medium', 'low'].includes(s) ? s : 'low';
  };

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  // Decode Windows HTML entities (&#9; tabs, &#13;&#10; CRLF, etc.)
  const decodeEntities = (s) => {
    if (!s) return '';
    const el = document.createElement('textarea');
    el.innerHTML = s;
    return el.value;
  };

  const squish = (s) => String(s || '').replace(/[\t\r\n]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
  const cleanText = (s) => squish(decodeEntities(String(s || '')));
  const short = (s, n = 220) => {
    const x = cleanText(s);
    return (x.length > n) ? (x.slice(0, n - 1) + '…') : x;
  };

  function setModeBadge() {
    const m = getMode().toUpperCase();
    modeBadge.textContent = m;
    modeBadge.className = 'badge ' + (m === 'LIVE' ? 'badge-live' : 'badge-sample');
  }

  async function checkHasData() {
    try {
      const r = await fetch(api('/last-scan'), { headers: { 'X-OCCT-No-Loader': '1' }, cache: 'no-store' });
      const j = await r.json();
      const ok = !!j?.has_data;
      noDataBanner.classList.toggle('hidden', ok);
      const span = noDataBanner.querySelector('.mode'); if (span) span.textContent = getMode().toUpperCase();
      return ok;
    } catch {
      noDataBanner.classList.remove('hidden');
      const span = noDataBanner.querySelector('.mode'); if (span) span.textContent = getMode().toUpperCase();
      return false;
    }
  }

  /* ---------- loaders ---------- */
  async function loadAlerts() {
    const qs = new URLSearchParams();
    if (fSeverity?.value) qs.set('severity', fSeverity.value);
    if (fStatus?.value)   qs.set('status', fStatus.value);
    if (fRule?.value?.trim()) qs.set('rule_id', fRule.value.trim());
    if (fQAlerts?.value?.trim()) qs.set('q', fQAlerts.value.trim());
    qs.set('limit', String(limit));
    qs.set('page', String(alertsPage));

    const r = await fetch(api('/detections') + '?' + qs.toString(), { headers: { 'X-OCCT-No-Loader': '1' }, cache: 'no-store' });
    const j = await r.json().catch(() => ({ items: [], total: 0 }));

    alertsTotal = j.total || 0;
    const maxPage = Math.max(1, Math.ceil((alertsTotal || 0) / limit));
    alertsPrev.disabled = alertsPage <= 1;
    alertsNext.disabled = alertsPage >= maxPage;
    alertsPageEl.textContent = `Page ${alertsPage}`;

    alertsTbody.innerHTML = '';
    (j.items || []).forEach((row) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(fmtTime(row.when))}</td>
        <td><span class="sev ${sevClass(row.severity)}">${esc((row.severity || '').toUpperCase())}</span></td>
        <td>${esc(row.rule_id || '—')}</td>
        <td title="${esc(cleanText(row.summary || ''))}">${esc(short(row.summary || '', 120))}</td>
        <td>${esc(cleanText(row.account || '—'))}</td>
        <td>${esc(cleanText(row.ip || '—'))}</td>
        <td><span class="status">${esc(row.status || 'new')}</span></td>
        <td class="nowrap"><button class="btn-secondary btn-sm" data-expand>Details</button></td>
      `;
      alertsTbody.appendChild(tr);

      const evidObj = (typeof row.evidence === 'string')
        ? (() => { try { return JSON.parse(row.evidence); } catch { return {}; } })()
        : (row.evidence || {});
      const det = document.createElement('tr');
      det.className = 'detail-row hidden';
      const pretty = JSON.stringify({
        id: row.id,
        when: row.when,
        rule_id: row.rule_id,
        severity: row.severity,
        status: row.status,
        account: cleanText(row.account || undefined),
        ip: cleanText(row.ip || undefined),
        evidence: evidObj,
      }, null, 2).slice(0, 4000);
      det.innerHTML = `<td colspan="8"><pre>${esc(pretty)}</pre></td>`;
      alertsTbody.appendChild(det);
    });
  }

  async function loadEvents() {
    const qs = new URLSearchParams();
    if (fEventId?.value?.trim()) qs.set('event_id', fEventId.value.trim());
    if (fAccount?.value?.trim()) qs.set('account', fAccount.value.trim());
    if (fIp?.value?.trim()) qs.set('ip', fIp.value.trim());
    if (fQEvents?.value?.trim()) qs.set('q', fQEvents.value.trim());
    qs.set('limit', String(limit));
    qs.set('page', String(eventsPage));

    const r = await fetch(api('/events') + '?' + qs.toString(), { headers: { 'X-OCCT-No-Loader': '1' }, cache: 'no-store' });
    const j = await r.json().catch(() => ({ items: [], total: 0 }));

    eventsTotal = j.total || 0;
    const maxPage = Math.max(1, Math.ceil((eventsTotal || 0) / limit));
    eventsPrev.disabled = eventsPage <= 1;
    eventsNext.disabled = eventsPage >= maxPage;
    eventsPageEl.textContent = `Page ${eventsPage}`;

    eventsTbody.innerHTML = '';
    (j.items || []).forEach((row) => {
      const accountText = cleanText(row.account || row.target || '—');
      const ipText      = cleanText(row.ip || 'N/A');      // <- N/A when missing
      const msgFull     = cleanText(row.message || '');
      const msgShort    = short(msgFull, 260);
      const hostText    = cleanText(row.host || '—');

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${esc(fmtTime(row.time))}</td>
        <td>${esc(row.event_id)}</td>
        <td>${esc(accountText)}</td>
        <td>${esc(ipText)}</td>
        <td title="${esc(msgFull)}">${esc(msgShort)}</td>
        <td>${esc(hostText)}</td>
        <td class="nowrap"><button class="btn-secondary btn-sm" data-expand>Details</button></td>
      `;
      eventsTbody.appendChild(tr);

      const detailObj = {
        record_id: row.record_id,
        provider: cleanText(row.provider || ''),
        channel: row.channel || 'Security',
        level: row.level || undefined,
        event_id: row.event_id,
        time: row.time,
        account: accountText !== '—' ? accountText : undefined,
        ip: ipText !== 'N/A' ? ipText : undefined,
        host: hostText !== '—' ? hostText : undefined,
        message_full: row.message ? cleanText(row.message) : '',
      };
      const det = document.createElement('tr');
      det.className = 'detail-row hidden';
      det.innerHTML = `<td colspan="7"><pre>${esc(JSON.stringify(detailObj, null, 2))}</pre></td>`;
      eventsTbody.appendChild(det);
    });
  }

  /* ---------- table interactions ---------- */
  function wireDelegates() {
    const toggleNextDetail = (tbody, e) => {
      const btn = e.target && e.target.closest('button[data-expand]');
      if (!btn) return;
      const row = btn.closest('tr');
      const detail = row && row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row')
        ? row.nextElementSibling
        : null;
      if (detail) detail.classList.toggle('hidden');
    };
    alertsTbody.addEventListener('click', (e) => toggleNextDetail(alertsTbody, e));
    eventsTbody.addEventListener('click', (e) => toggleNextDetail(eventsTbody, e));
  }

  /* ---------- tabs ---------- */
  function showAlerts() {
    tabAlerts.classList.add('active'); tabEvents.classList.remove('active');
    alertsPane.classList.remove('hidden'); eventsPane.classList.add('hidden');
    $('.filters .for-alerts').classList.remove('hidden');
    $('.filters .for-events').classList.add('hidden');
  }
  function showEvents() {
    tabEvents.classList.add('active'); tabAlerts.classList.remove('active');
    eventsPane.classList.remove('hidden'); alertsPane.classList.add('hidden');
    $('.filters .for-events').classList.remove('hidden');
    $('.filters .for-alerts').classList.add('hidden');
  }

  /* ---------- wire UI ---------- */
  tabAlerts.addEventListener('click', showAlerts);
  tabEvents.addEventListener('click', showEvents);

  btnSearchAl.addEventListener('click', () => { alertsPage = 1; loadAlerts(); });
  btnClearAl.addEventListener('click', () => {
    if (fSeverity) fSeverity.value = '';
    if (fStatus)   fStatus.value = '';
    if (fRule)     fRule.value = '';
    if (fQAlerts)  fQAlerts.value = '';
    alertsPage = 1; loadAlerts();
  });

  btnSearchEv.addEventListener('click', () => { eventsPage = 1; loadEvents(); });
  btnClearEv.addEventListener('click', () => {
    if (fEventId) fEventId.value = '';
    if (fAccount) fAccount.value = '';
    if (fIp)      fIp.value = '';
    if (fQEvents) fQEvents.value = '';
    eventsPage = 1; loadEvents();
  });

  alertsPrev.addEventListener('click', () => { if (alertsPage > 1) { alertsPage--; loadAlerts(); } });
  alertsNext.addEventListener('click', () => {
    const maxPage = Math.max(1, Math.ceil((alertsTotal || 0) / limit));
    if (alertsPage < maxPage) { alertsPage++; loadAlerts(); }
  });

  eventsPrev.addEventListener('click', () => { if (eventsPage > 1) { eventsPage--; loadEvents(); } });
  eventsNext.addEventListener('click', () => {
    const maxPage = Math.max(1, Math.ceil((eventsTotal || 0) / limit));
    if (eventsPage < maxPage) { eventsPage++; loadEvents(); }
  });

  window.addEventListener('storage', (e) => { if (e.key === K.MODE) init(); });

  async function init() {
    setModeBadge();
    wireDelegates();
    await checkHasData();
    await loadAlerts();
    await loadEvents();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
