// --- Mock data until backend API is ready ---
const RAW = [
  { time: "2025-04-22T17:45:00Z", category: "System",  control: "Service hardening",             outcome: "Failed",  account: "SRV-WS001", description: "Unexpected service enabled: Telnet" },
  { time: "2025-04-22T16:20:00Z", category: "Security",control: "Password complexity",          outcome: "Passed",  account: "AD-Policy", description: "Complexity enabled per policy" },
  { time: "2025-04-22T14:05:00Z", category: "Account", control: "Dormant account disable",       outcome: "Failed",  account: "j.smith",   description: "Account inactive 120+ days" },
  { time: "2025-04-22T12:37:00Z", category: "System",  control: "Firewall enabled",              outcome: "Passed",  account: "SRV-WS001", description: "All profiles enabled" },
  { time: "2025-04-22T12:30:00Z", category: "Account", control: "MFA enforced",                  outcome: "Passed",  account: "All users", description: "90% MFA coverage" },
  { time: "2025-04-21T10:01:00Z", category: "Security",control: "Minimum password length",       outcome: "Failed",  account: "Domain",    description: "Observed 8, expected >=14" },
  { time: "2025-04-20T09:12:00Z", category: "System",  control: "SMB signing required",          outcome: "Passed",  account: "SRV-FS01",  description: "Enforced via GPO" }
];

// --- Elements ---
const tbody = document.getElementById('auditTableBody');
const q = document.getElementById('q');
const dateFrom = document.getElementById('dateFrom');
const dateTo = document.getElementById('dateTo');
const outcome = document.getElementById('outcome');
const chips = [...document.querySelectorAll('.chip')];
const resultCount = document.getElementById('resultCount');
const prevPage = document.getElementById('prevPage');
const nextPage = document.getElementById('nextPage');
const pageInfo = document.getElementById('pageInfo');
const exportBtn = document.getElementById('exportBtn');
const clearBtn = document.getElementById('clearBtn');
const headers = [...document.querySelectorAll('thead th')];

// --- State ---
let sortKey = 'time';
let sortDir = 'desc';
let page = 1;
const pageSize = 8;
const activeCats = new Set();

// --- Helpers ---
const fmtTime = iso => {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) +
         ' ' + d.toLocaleDateString();
};
const cmp = (a,b,k) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0);

// --- Filtering + sorting ---
function filtered() {
  const text = q.value.trim().toLowerCase();
  const from = dateFrom.value ? new Date(dateFrom.value) : null;
  const to   = dateTo.value   ? new Date(dateTo.value + "T23:59:59") : null;
  const oc   = outcome.value;

  return RAW.filter(r => {
    if (activeCats.size && !activeCats.has(r.category)) return false;
    if (oc && r.outcome !== oc) return false;
    const d = new Date(r.time);
    if (from && d < from) return false;
    if (to && d > to) return false;
    if (text) {
      const hay = (r.description + ' ' + r.control + ' ' + r.account + ' ' + r.category)
                    .toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  }).sort((a,b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    if (sortKey === 'time') return (new Date(a.time) - new Date(b.time)) * dir;
    return cmp(a,b,sortKey) * dir;
  });
}

function render() {
  const rows = filtered();
  resultCount.textContent = rows.length;

  // paginate
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);

  // rows
  tbody.innerHTML = slice.map(r => `
    <tr>
      <td>${fmtTime(r.time)}</td>
      <td>${badge(r.category)}</td>
      <td>${escapeHTML(r.control)}</td>
      <td>${outcomePill(r.outcome)}</td>
      <td>${escapeHTML(r.account)}</td>
      <td>${escapeHTML(r.description)}</td>
    </tr>
  `).join('');

  // pager
  pageInfo.textContent = `${page} / ${totalPages}`;
  prevPage.disabled = page <= 1;
  nextPage.disabled = page >= totalPages;
}

function badge(cat){
  const cls = cat === 'System' ? 'sys' : cat === 'Security' ? 'sec' : 'acc';
  return `<span class="badge ${cls}">${cat}</span>`;
}
function outcomePill(o){
  return `<span class="outcome ${o === 'Passed' ? 'pass' : 'fail'}">${o}</span>`;
}
function escapeHTML(s){
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// --- Events ---
q.addEventListener('input', () => { page = 1; render(); });
dateFrom.addEventListener('change', () => { page = 1; render(); });
dateTo.addEventListener('change', () => { page = 1; render(); });
outcome.addEventListener('change', () => { page = 1; render(); });

chips.forEach(ch => {
  ch.addEventListener('click', () => {
    const cat = ch.dataset.cat;
    if (activeCats.has(cat)) { activeCats.delete(cat); ch.classList.remove('active'); }
    else { activeCats.add(cat); ch.classList.add('active'); }
    page = 1; render();
  });
});

prevPage.addEventListener('click', () => { if (page>1) { page--; render(); } });
nextPage.addEventListener('click', () => { page++; render(); });

headers.forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (!key) return;
    if (sortKey === key) sortDir = (sortDir === 'asc' ? 'desc' : 'asc');
    else { sortKey = key; sortDir = key === 'time' ? 'desc' : 'asc'; }
    render();
  });
});

clearBtn.addEventListener('click', () => {
  q.value = ''; dateFrom.value = ''; dateTo.value = ''; outcome.value = '';
  activeCats.clear(); chips.forEach(c => c.classList.remove('active')); page = 1; render();
});

exportBtn.addEventListener('click', () => {
  const rows = filtered();
  const header = ['Time','Category','Control','Outcome','Account/Host','Description'];
  const csv = [header.join(',')].concat(rows.map(r =>
    [
      new Date(r.time).toISOString(),
      r.category,
      r.control.replaceAll('"','""'),
      r.outcome,
      r.account.replaceAll('"','""'),
      r.description.replaceAll('"','""')
    ].map(x => `"${x}"`).join(',')
  )).join('\n');

  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `occt_audit_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// initial render
render();
