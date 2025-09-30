// Audit Trail page logic: loads data from API (sample/live via window.occt.api),
// supports search, category chips, outcome filter, sort, pagination, and CSV export.
// (Date filters removed because scans are batch-only.)

// --- Elements ---
const tbody       = document.getElementById('auditTableBody');
const q           = document.getElementById('q');
const outcome     = document.getElementById('outcome');
const chips       = [...document.querySelectorAll('.chip')];
const resultCount = document.getElementById('resultCount');
const prevPage    = document.getElementById('prevPage');
const nextPage    = document.getElementById('nextPage');
const pageInfo    = document.getElementById('pageInfo');
const exportBtn   = document.getElementById('exportBtn');
const clearBtn    = document.getElementById('clearBtn');
const headers     = [...document.querySelectorAll('thead th')];

// --- State ---
let DATA = [];            // populated from API
let sortKey = 'time';
let sortDir = 'desc';
let page = 1;
const pageSize = 12;
const activeCats = new Set();

// --- API helper (falls back to samples if site.js not present) ---
const api = (window.occt && window.occt.api)
  ? window.occt.api
  : (p => '/api/sample' + p);

// --- Utils ---
const escapeHTML = (s='') =>
  s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));

const fmtTime = (iso) => {
  if (!iso) return '';
  if (window.occt && typeof window.occt.formatDateTimeAU === 'function') {
    return window.occt.formatDateTimeAU(iso);
  }
  const d = new Date(iso);
  const date = d.toLocaleDateString('en-AU', { timeZone: 'Australia/Sydney' });
  const time = d.toLocaleTimeString('en-AU', { timeZone: 'Australia/Sydney', hour:'2-digit', minute:'2-digit', hour12:false });
  return `${time} ${date}`;
};

const cmp = (a,b,k) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0);

// Badge/outcome classes
const badge = cat => {
  const cls = cat === 'System' ? 'sys' : cat === 'Security' ? 'sec' : 'acc';
  return `<span class="badge ${cls}">${escapeHTML(cat || '')}</span>`;
};
const outcomePill = o =>
  `<span class="outcome ${o === 'Passed' ? 'pass' : 'fail'}">${escapeHTML(o || '')}</span>`;

// --- Fetch + normalize data from API ---
async function loadData() {
  tbody.innerHTML = `<tr><td colspan="6">Loading…</td></tr>`;
  try {
    const res = await fetch(api('/audit'));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const json = await res.json();
    // Expect an array of records; normalize keys defensively.
    // Add `code` so search can match project codes (e.g., FIA_AFL.1).
    DATA = (Array.isArray(json) ? json : []).map(r => ({
      time:        r.time || r.timestamp || null,
      category:    r.category || '',
      control:     r.control || r.check_name || '',
      outcome:     r.outcome || r.status || '',
      account:     r.account || r.host || '',
      description: r.description || '',
      code:        r.code || r.cc || r.cc_id || ''   // <-- project code support
    }));
  } catch (err) {
    console.error('Audit load failed:', err);
    DATA = [];
    tbody.innerHTML = `<tr><td colspan="6">Failed to load audit data.</td></tr>`;
  }
}

// --- Filtering + sorting (no date range) ---
function filtered() {
  const text = (q?.value || '').trim().toLowerCase();
  const oc   = outcome?.value || '';

  return DATA.filter(r => {
    if (activeCats.size && !activeCats.has(r.category)) return false;
    if (oc && r.outcome !== oc) return false;

    if (text) {
      const hay = `${r.description} ${r.control} ${r.account} ${r.category} ${r.code}`.toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  }).sort((a,b) => {
    const dir = (sortDir === 'asc') ? 1 : -1;
    if (sortKey === 'time') {
      const at = a.time ? new Date(a.time).getTime() : 0;
      const bt = b.time ? new Date(b.time).getTime() : 0;
      return (at - bt) * dir;
    }
    return cmp(a,b,sortKey) * dir;
  });
}

function render() {
  const rows = filtered();
  if (resultCount) resultCount.textContent = rows.length;

  // paginate
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);

  // rows
  if (!slice.length) {
    tbody.innerHTML = `<tr><td colspan="6">No results.</td></tr>`;
  } else {
    tbody.innerHTML = slice.map(r => `
      <tr>
        <td>${fmtTime(r.time)}</td>
        <td>${badge(r.category)}</td>
        <td>${escapeHTML(r.control)}</td>
        <td>${outcomePill(r.outcome)}</td>
        <td>${escapeHTML(r.account)}</td>
        <td>
          ${escapeHTML(r.description)}
          ${r.code ? `<div class="code-line">${escapeHTML(r.code)}</div>` : ''}
        </td>
      </tr>
    `).join('');
  }

  // pager
  if (pageInfo) pageInfo.textContent = `${page} / ${totalPages}`;
  if (prevPage) prevPage.disabled = page <= 1;
  if (nextPage) nextPage.disabled = page >= totalPages;
}

// --- Events ---
if (q) q.addEventListener('input', () => { page = 1; render(); });
if (outcome) outcome.addEventListener('change', () => { page = 1; render(); });

chips.forEach(ch => {
  ch.addEventListener('click', () => {
    const cat = ch.dataset.cat;
    if (!cat) return;
    if (activeCats.has(cat)) { activeCats.delete(cat); ch.classList.remove('active'); }
    else { activeCats.add(cat); ch.classList.add('active'); }
    page = 1; render();
  });
});

if (prevPage) prevPage.addEventListener('click', () => { if (page>1) { page--; render(); } });
if (nextPage) nextPage.addEventListener('click', () => { page++; render(); });

headers.forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (!key) return;
    if (sortKey === key) sortDir = (sortDir === 'asc' ? 'desc' : 'asc');
    else { sortKey = key; sortDir = key === 'time' ? 'desc' : 'asc'; }
    render();
  });
});

if (clearBtn) clearBtn.addEventListener('click', () => {
  if (q) q.value = '';
  if (outcome) outcome.value = '';
  activeCats.clear(); chips.forEach(c => c.classList.remove('active'));
  page = 1; render();
});

if (exportBtn) exportBtn.addEventListener('click', () => {
  const rows = filtered();
  const header = ['Time','Category','Control','Outcome','Account/Host','Description','Code'];
  const csv = [header.join(',')].concat(
    rows.map(r => [
      r.time ? new Date(r.time).toISOString() : '', // ISO for machine-readability
      r.category,
      (r.control || '').replaceAll('"','""'),
      r.outcome,
      (r.account || '').replaceAll('"','""'),
      (r.description || '').replaceAll('"','""'),
      (r.code || '').replaceAll('"','""')
    ].map(x => `"${x}"`).join(','))
  ).join('\n');

  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `occt_audit_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// --- Init ---
(async function init(){
  await loadData();
  render();
})();
