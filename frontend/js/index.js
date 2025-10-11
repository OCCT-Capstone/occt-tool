// frontend/js/index.js
(async () => {
  // ---------- Helpers ----------
  const api = (window.occt && window.occt.api)
    ? window.occt.api
    : (p => '/api/sample' + p); // fallback to samples if site.js not present

  const escapeHTML = (s='') =>
    s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  const badgeClass = (cat) => (cat === 'System' ? 'sys' : (cat === 'Security' ? 'sec' : 'acc'));
  const toNum  = (v, d = 0) => (typeof v === 'number' && !Number.isNaN(v)) ? v : d;
  const round0 = (n) => Math.round(n);
  const sevRank = s => ({ high:3, medium:2, low:1 }[String(s||'').toLowerCase()] || 0);
  const outRank = o => ({ failed:2, fail:2, passed:1, pass:1 }[String(o||'').toLowerCase()] || 0);

  // ---------- Fetch dashboard + audit + rules (for severity enrichment) ----------
  try {
    const [dashRes, auditRes, rulesRes] = await Promise.all([
      fetch(api('/dashboard')),
      fetch(api('/audit')),
      fetch(api('/rules')).catch(() => ({ ok:false }))
    ]);
    if (!dashRes.ok)  throw new Error('Dashboard HTTP ' + dashRes.status);
    if (!auditRes.ok) throw new Error('Audit HTTP ' + auditRes.status);

    const dash  = await dashRes.json();
    const audit = await auditRes.json();
    const rules = rulesRes && rulesRes.ok ? await rulesRes.json() : [];

    const sevMap = new Map(
      Array.isArray(rules)
        ? rules.map(r => [ (r.title || r.id || '').trim(), (r.severity || '').toLowerCase() ])
        : []
    );
    const rowSeverityRank = (r) => sevRank(r.severity || sevMap.get((r.control || r.title || '').trim()));

    // ===== Passed/Failed/Total (prefer API summary; else derive from audit rows) =====
    let passed = null, failed = null, total = null;
    if (dash?.summary) {
      if (typeof dash.summary.passed_count === 'number') passed = dash.summary.passed_count;
      if (typeof dash.summary.failed_count === 'number') failed = dash.summary.failed_count;
      if (typeof dash.summary.total_checks === 'number') total = dash.summary.total_checks;
    }
    if (total == null || passed == null || failed == null) {
      const list = Array.isArray(audit) ? audit : [];
      const f = list.filter(r => (r.outcome || '').toLowerCase() === 'failed').length;
      const t = list.length;
      const p = Math.max(t - f, 0);
      if (failed == null) failed = f;
      if (total  == null) total  = t;
      if (passed == null) passed = p;
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
    compliancePct = round0(compliancePct);

    // ===== Donut =====
    const donutValueEl = document.getElementById('donut-value');
    const pctTextEl    = document.getElementById('nonCompliantPct'); // UI label says "Compliance"
    if (donutValueEl) donutValueEl.setAttribute('stroke-dasharray', `${toNum(compliancePct, 0)}, 100`);
    if (pctTextEl)     pctTextEl.textContent = `${toNum(compliancePct, 0)}%`;

    // ===== Bars (stacked) =====
    const monthly = Array.isArray(dash?.monthly) ? dash.monthly : [];
    const barChart = document.getElementById('barChart');
    const axisX    = document.getElementById('axisX');
    if (barChart) barChart.innerHTML = '';
    if (axisX) axisX.innerHTML = '';

    monthly.forEach((pt) => {
      const rawC = Number(pt.compliant) || 0;
      const rawN = Number(pt.noncompliant) || 0;
      const tot  = rawC + rawN;

      const cPct = tot > 0 ? (rawC / tot) * 100 : 0;
      const nPct = tot > 0 ? (rawN / tot) * 100 : 0;

      const col = document.createElement('div');
      col.className = 'barcol';
      col.setAttribute('role', 'img');
      col.setAttribute('aria-label', `${pt.month || 'Month'}: ${cPct.toFixed(0)}% compliant, ${nPct.toFixed(0)}% non-compliant`);
      col.title = `${pt.month || ''}: ${cPct.toFixed(0)}% compliant • ${nPct.toFixed(0)}% non-compliant`;

      const red = document.createElement('div');   red.className = 'bar red';   red.style.height = nPct + '%';
      const green = document.createElement('div'); green.className = 'bar green'; green.style.height = cPct + '%';
      const lblGreen = document.createElement('div'); lblGreen.className = 'bar-label bottom'; lblGreen.textContent = `${cPct.toFixed(0)}%`;

      col.append(red, green, lblGreen);
      barChart.appendChild(col);

      const tick = document.createElement('span');
      tick.textContent = pt.month || '';
      axisX.appendChild(tick);
    });

    // ===== KPIs =====
    const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = (val ?? '—'); };
    setTxt('kpiTotal',   (typeof total  === 'number') ? String(total)  : '—');
    setTxt('kpiPassed',  (typeof passed === 'number') ? String(passed) : '0');
    setTxt('kpiFailed',  (typeof failed === 'number') ? String(failed) : '0');
    setTxt('kpiIssues',        (typeof failed === 'number') ? String(failed) : '0');
    setTxt('kpiIssuesDetail',  (typeof failed === 'number') ? String(failed) : '0');

    // distinct accounts
    const accounts = Array.isArray(audit)
      ? new Set(audit.map(r => r.account).filter(Boolean)).size
      : 0;
    setTxt('kpiAccounts', accounts || '—');

    // ===== Audit preview (top 5) — Failed → Severity → Control =====
    const preview = document.getElementById('auditPreview');
    const rows = (Array.isArray(audit) ? audit : []).slice();

    rows.sort((a,b) => {
      const oc = outRank(b.outcome) - outRank(a.outcome); if (oc) return oc;
      const sc = rowSeverityRank(b) - rowSeverityRank(a); if (sc) return sc;
      const an = (a.control || '').toLowerCase();
      const bn = (b.control || '').toLowerCase();
      return an.localeCompare(bn);
    });

    const top = rows.slice(0, 5);
    if (preview) {
      preview.innerHTML = `
        <div class="thead">
          <div>Time</div><div>Category</div><div>Description</div>
        </div>
        ${top.map(r => `
          <div class="trow" data-cat="${escapeHTML(r.category || '')}">
            <div>${fmtTime(r.time)}</div>
            <div><span class="badge ${badgeClass(r.category)}">${escapeHTML(r.category || '')}</span></div>
            <div class="desc" title="${escapeHTML(r.description || '')}">${escapeHTML(r.description || '')}</div>
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
