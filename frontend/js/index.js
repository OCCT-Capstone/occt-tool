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

    // ===== Donut =====
    const pct = Number(dash?.summary?.non_compliant_percent ?? 0);
    document.getElementById('donut-value')
        .setAttribute('stroke-dasharray', `${pct}, 100`);
    document.getElementById('nonCompliantPct').textContent = `${pct}%`;

    // ===== Bars =====
    const monthly = Array.isArray(dash?.monthly) ? dash.monthly : [];
    const barChart = document.getElementById('barChart');
    const axisX = document.getElementById('axisX');
    barChart.innerHTML = '';
    axisX.innerHTML = '';

    monthly.forEach(pt => {
        const col = document.createElement('div');
        col.className = 'barcol';

        const green = document.createElement('div');
        green.className = 'bar green';
        green.style.height = (Number(pt.compliant) || 0) + '%';

        const red = document.createElement('div');
        red.className = 'bar red';
        red.style.height = (Number(pt.noncompliant) || 0) + '%';

        col.appendChild(green);
        col.appendChild(red);
        barChart.appendChild(col);

        const tick = document.createElement('span');
        tick.textContent = pt.month || '';
        axisX.appendChild(tick);
    });

    // ===== KPIs (optional demo values using audit list) =====
    // You can replace this with real totals from your backend when available.
    const total = Array.isArray(audit) ? audit.length : 0;
    const passed = Array.isArray(audit) ? audit.filter(r => r.outcome === 'Passed').length : 0;
    const failed = total - passed;

    document.getElementById('kpiTotal').textContent = total || '—';
    document.getElementById('kpiPassed').textContent = passed || '0';
    document.getElementById('kpiFailed').textContent = failed || '0';
    document.getElementById('kpiIssues').textContent = failed || '0';
    document.getElementById('kpiIssuesDetail').textContent = failed ? String(failed) : '0';
    // If you track distinct accounts, set kpiAccounts accordingly
    const accounts = Array.isArray(audit)
        ? new Set(audit.map(r => r.account).filter(Boolean)).size
        : 0;
    document.getElementById('kpiAccounts').textContent = accounts || '—';

    // ===== Audit preview (top 5 rows) =====
    const preview = document.getElementById('auditPreview');
    const top = (Array.isArray(audit) ? audit : []).slice(0, 5);

    preview.innerHTML = `
        <div class="thead">
        <div>Time</div><div>Category</div><div>Description</div>
        </div>
        ${top.map(r => `
        <div class="trow">
            <div>${fmtTime(r.time)}</div>
            <div><span class="badge ${badgeClass(r.category)}">${escapeHTML(r.category || '')}</span></div>
            <div>${escapeHTML(r.description || '')}</div>
        </div>
        `).join('')}
    `;
    } catch (err) {
    console.error('Dashboard load failed:', err);
    // Minimal fallback so the page still looks okay
    document.getElementById('nonCompliantPct').textContent = '—';
    }
})();
