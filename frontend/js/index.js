// frontend/js/index.js
(async () => {
  // ---------- Helpers ----------
  const api = (window.occt && window.occt.api)
    ? window.occt.api
    : (p => '/api/sample' + p); // fallback to samples if site.js not present

  function escapeHTML(s = '') {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }
  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  function badgeClass(cat) {
    return cat === 'System' ? 'sys' : cat === 'Security' ? 'sec' : 'acc';
  }
  const toNum  = (v, d = 0) => (typeof v === 'number' && !Number.isNaN(v)) ? v : d;
  const round0 = (n) => Math.round(n);

  // ---------- Fetch both dashboard + audit preview ----------
  try {
    const [dashRes, auditRes] = await Promise.all([
      fetch(api('/dashboard')),
      fetch(api('/audit'))
    ]);
    if (!dashRes.ok)  throw new Error('Dashboard HTTP ' + dashRes.status);
    if (!auditRes.ok) throw new Error('Audit HTTP ' + auditRes.status);

    const dash  = await dashRes.json();
    const audit = await auditRes.json();

    // ===== Passed/Failed/Total (prefer API summary counts; else derive from audit array) =====
    let passed = null, failed = null, total = null;

    if (dash?.summary) {
      if (typeof dash.summary.passed_count === 'number') passed = dash.summary.passed_count;
      if (typeof dash.summary.failed_count === 'number') failed = dash.summary.failed_count;
      if (typeof dash.summary.total_checks === 'number') total = dash.summary.total_checks;
    }
    if (total == null || passed == null || failed == null) {
      const list = Array.isArray(audit) ? audit : [];
      const failedFromRows = list.filter(r => (r.outcome || '').toLowerCase() === 'failed').length;
      const totalFromRows  = list.length;
      const passedFromRows = Math.max(totalFromRows - failedFromRows, 0);
      if (failed == null) failed = failedFromRows;
      if (total  == null) total  = totalFromRows;
      if (passed == null) passed = passedFromRows;
    }

    // ===== Compliance % (0 dp) =====
    let compliancePct;
    if (typeof dash?.summary?.compliant_percent === 'number') {
      compliancePct = dash.summary.compliant_percent;
    } else if (typeof dash?.summary?.non_compliant_percent === 'number') {
      compliancePct = 100 - dash.summary.non_compliant_percent;
    } else if (typeof total === 'number' && total > 0 && typeof passed === 'number') {
      compliancePct = (passed / total) * 100;
    } else {
      compliancePct = 0;
    }
    compliancePct = round0(compliancePct); // <- 0 decimal places

    // ===== Donut (gauge) =====
    const donutValueEl = document.getElementById('donut-value');
    const pctTextEl    = document.getElementById('nonCompliantPct'); // label says Compliance in UI
    if (donutValueEl) donutValueEl.setAttribute('stroke-dasharray', `${toNum(compliancePct, 0)}, 100`);
    if (pctTextEl)     pctTextEl.textContent = `${toNum(compliancePct, 0)}%`;  // replace, don't append

  // ===== Bars (stacked columns) with % label (green only) =====
  const monthly = Array.isArray(dash?.monthly) ? dash.monthly : [];
  const barChart = document.getElementById('barChart');
  const axisX    = document.getElementById('axisX');
  if (barChart) barChart.innerHTML = '';
  if (axisX) axisX.innerHTML = '';

  monthly.forEach((pt) => {
    const rawC = Number(pt.compliant) || 0;
    const rawN = Number(pt.noncompliant) || 0;
    const total = rawC + rawN;

    // Support either counts or percentages by normalizing
    const cPct = total > 0 ? (rawC / total) * 100 : 0;
    const nPct = total > 0 ? (rawN / total) * 100 : 0;

    const col = document.createElement('div');
    col.className = 'barcol';
    col.setAttribute('role', 'img');
    // Keep full info in accessibility/tooltip, even if we hide red visually
    col.setAttribute('aria-label', `${pt.month || 'Month'}: ${cPct.toFixed(0)}% compliant, ${nPct.toFixed(0)}% non-compliant`);
    col.title = `${pt.month || ''}: ${cPct.toFixed(0)}% compliant • ${nPct.toFixed(0)}% non-compliant`;

    // Segments: red on top, green on bottom
    const red = document.createElement('div');
    red.className = 'bar red';
    red.style.height = nPct + '%';

    const green = document.createElement('div');
    green.className = 'bar green';
    green.style.height = cPct + '%';

    // Visible label: ONLY compliant (green) %
    const lblGreen = document.createElement('div');
    lblGreen.className = 'bar-label bottom';
    lblGreen.textContent = `${cPct.toFixed(0)}%`;

    // Append order defines stacking (top -> bottom)
    col.appendChild(red);
    col.appendChild(green);
    col.appendChild(lblGreen);

    barChart.appendChild(col);

    const tick = document.createElement('span');
    tick.textContent = pt.month || '';
    axisX.appendChild(tick);
  });




    // ===== KPIs (use textContent so we don't keep the old '—' placeholder) =====
    const setTxt = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = (val ?? '—');
    };
    setTxt('kpiTotal',   (typeof total  === 'number') ? String(total)  : '—');
    setTxt('kpiPassed',  (typeof passed === 'number') ? String(passed) : '0');
    setTxt('kpiFailed',  (typeof failed === 'number') ? String(failed) : '0');
    setTxt('kpiIssues',        (typeof failed === 'number') ? String(failed) : '0');
    setTxt('kpiIssuesDetail',  (typeof failed === 'number') ? String(failed) : '0');

    // Accounts (distinct) from audit rows
    const accounts = Array.isArray(audit)
      ? new Set(audit.map(r => r.account).filter(Boolean)).size
      : 0;
    setTxt('kpiAccounts', accounts || '—');

    // ===== Audit preview (top 5 rows) =====
    const preview = document.getElementById('auditPreview');
    const top = (Array.isArray(audit) ? audit : []).slice(0, 5);
    if (preview) {
      preview.innerHTML = `
        <div class="thead">
          <div>Time</div><div>Category</div><div>Description</div>
        </div>
        ${top.map(r => `
          <div class="trow">
            <div>${fmtTime(r.time)}</div>
            <div><span class="badge ${badgeClass(r.category)}">${escapeHTML(r.category || '')}</span></div>
            <div class="desc" title="${escapeHTML(r.description || '')}">
              ${escapeHTML(r.description || '')}
            </div>
          </div>
        `).join('')}
      `;
    }
  } catch (err) {
    console.error('Dashboard load failed:', err);
    const pctTextEl = document.getElementById('nonCompliantPct');
    if (pctTextEl) pctTextEl.textContent = '—';
  }
})();
