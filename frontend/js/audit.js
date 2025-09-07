/**
 * Audit Trail table interactivity
 * - Filters: text, date range, category chips, outcome select
 * - Sorting: by clicking table headers (data-sort attr)
 * - Pagination: simple client-side pages
 * - Export: current filtered set to CSV
 *
 * NOTE: RAW is mocked for now; later replace with fetch('/api/audit').
 */

// --- Mock data until backend API is ready ---
const RAW = [
  { time: "2025-04-22T17:45:00Z", category: "System",  control: "Service hardening",        outcome: "Failed", account: "SRV-WS001", description: "Unexpected service enabled: Telnet" },
  { time: "2025-04-22T16:20:00Z", category: "Security",control: "Password complexity",       outcome: "Passed", account: "AD-Policy", description: "Complexity enabled per policy" },
  { time: "2025-04-22T14:05:00Z", category: "Account", control: "Dormant account disable",   outcome: "Failed", account: "j.smith",   description: "Account inactive 120+ days" },
  { time: "2025-04-22T12:37:00Z", category: "System",  control: "Firewall enabled",          outcome: "Passed", account: "SRV-WS001", description: "All profiles enabled" },
  { time: "2025-04-22T12:30:00Z", category: "Account", control: "MFA enforced",              outcome: "Passed", account: "All users", description: "90% MFA coverage" },
  { time: "2025-04-21T10:01:00Z", category: "Security",control: "Minimum password length",   outcome: "Failed", account: "Domain",    description: "Observed 8, expected >=14" },
  { time: "2025-04-20T09:12:00Z", category: "System",  control: "SMB signing required",      outcome: "Passed", account: "SRV-FS01",  description: "Enforced via GPO" }
];

// --- Element references ---
const tbody      = document.getElementById('auditTableBody');
const q          = document.getElementById('q');
const dateFrom   = document.getElementById('dateFrom');
const dateTo     = document.getElementById('dateTo');
const outcome    = document.getElementById('outcome');
const chips      = [...document.querySelectorAll('.chip')];
const resultCount= document.getElementById('resultCount');
const prevPage   = document.getElementById('prevPage');
const nextPage   = document.getElementById('nextPage');
const pageInfo   = document.getElementById('pageInfo');
const exportBtn  = document.getElementById('exportBtn');
const clearBtn   = document.getElementById('clearBtn');
const headers    = [...document.querySelectorAll('thead th')];

// --- Table state ---
let sortKey = 'time';   // default sort by time
let sortDir = 'desc';   // newest first
let page    = 1;        // current page (1-indexed)
const pageSize  = 8;    // rows per page
const activeCats= new Set(); // selected category chips

// --- Helpers ---

/** Format ISO datetime into HH:MM + locale date */
const fmtTime = (iso) => {
  const d = new Date(iso);
  const hhmm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const date = d.toLocaleDateString();
  return `${hhmm} ${date}`;
};

/** Generic comparator for object keys */
const cmp = (a, b, k) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0);

/** HTML escape to prevent accidental injection in table cells */
function escapeHTML(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]
  ));
}

/** Category -> badge HTML */
function badge(cat){
  const cls = cat === 'System' ? 'sys' : (cat === 'Security' ? 'sec' : 'acc');
  return `<span class="badge ${cls}">${cat}</span>`;
}

/** Outcome -> pill HTML */
function outcomePill(o){
  return `<span class="outcome ${o === 'Passed' ? 'pass' : 'fail'}">${o}</span>`;
}

// --- Filtering + sorting ---

/**
 * Build a filtered + sorted array from RAW based on UI inputs.
 * - text in q (searches description/control/account/category)
 * - date range (inclusive)
 * - selected categories (chips)
 * - outcome (select)
 * - sortKey/sortDir
 */
function filtered() {
  const text = q.value.trim().toLowerCase();
  const from = dateFrom.value ? new Date(dateFrom.value) : null;
  const to   = dateTo.value   ? new Date(dateTo.value + "T23:59:59") : null;
  const oc   = outcome.value;

  // Filter
  const data = RAW.filter((r) => {
    if (activeCats.size && !activeCats.has(r.category)) return false;
    if (oc && r.outcome !== oc) return false;

    const d = new Date(r.time);
    if (from && d < from) return false;
    if (to   && d > to)   return false;

    if (text) {
      const hay = `${r.description} ${r.control} ${r.account} ${r.category}`.toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });

  // Sort
  const dir = (sortDir === 'asc') ? 1 : -1;
  return data.sort((a, b) => {
    if (sortKey === 'time') return (new Date(a.time) - new Date(b.time)) * dir;
    return cmp(a, b, sortKey) * dir;
  });
}

/** Render current page slice into <tbody> and update pager/count */
function render() {
  const rows = filtered();
  resultCount.textContent = rows.length;

  // Pagination math
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);

  // Rows HTML
  tbody.innerHTML = slice.map((r) => `
    <tr>
      <td>${fmtTime(r.time)}</td>
      <td>${badge(r.category)}</td>
      <td>${escapeHTML(r.control)}</td>
      <td>${outcomePill(r.outcome)}</td>
      <td>${escapeHTML(r.account)}</td>
      <td>${escapeHTML(r.description)}</td>
    </tr>
  `).join('');

  // Pager UI
  pageInfo.textContent = `${page} / ${totalPages}`;
  prevPage.disabled = page <= 1;
  nextPage.disabled = page >= totalPages;
}

// --- Event wiring ---

// Text / date / outcome filters
q.addEventListener('input',       () => { page = 1; render(); });
dateFrom.addEventListener('change', () => { page = 1; render(); });
dateTo.addEventListener('change',   () => { page = 1; render(); });
outcome.addEventListener('change',  () => { page = 1; render(); });

// Category chips
chips.forEach((ch) => {
  ch.addEventListener('click', () => {
    const cat = ch.dataset.cat;
    if (activeCats.has(cat)) {
      activeCats.delete(cat);
      ch.classList.remove('active');
    } else {
      activeCats.add(cat);
      ch.classList.add('active');
    }
    page = 1;
    render();
  });
});

// Paging
prevPage.addEventListener('click', () => { if (page > 1) { page--; render(); } });
nextPage.addEventListener('click', () => { page++; render(); });

// Sorting by header click
headers.forEach((th) => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (!key) return; // non-sortable column (e.g., Description)

    if (sortKey === key) {
      // Toggle direction on repeated click
      sortDir = (sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      // Switch key; default desc for time, asc otherwise
      sortKey = key;
      sortDir = (key === 'time') ? 'desc' : 'asc';
    }
    render();
  });
});

// Clear all filters
clearBtn.addEventListener('click', () => {
  q.value = '';
  dateFrom.value = '';
  dateTo.value = '';
  outcome.value = '';
  activeCats.clear();
  chips.forEach((c) => c.classList.remove('active'));
  page = 1;
  render();
});

// Export filtered rows to CSV
exportBtn.addEventListener('click', () => {
  const rows = filtered();
  const header = ['Time','Category','Control','Outcome','Account/Host','Description'];

  // Quote fields and escape quotes per CSV convention
  const csv = [header.join(',')]
    .concat(rows.map((r) => ([
      new Date(r.time).toISOString(),
      r.category,
      r.control.replaceAll('"','""'),
      r.outcome,
      r.account.replaceAll('"','""'),
      r.description.replaceAll('"','""')
    ].map((x) => `"${x}"`).join(','))))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `occt_audit_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// Initial paint
render();
