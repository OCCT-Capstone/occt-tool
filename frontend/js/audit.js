// frontend/js/audit.js

// --- Elements ---
const tbody       = document.getElementById('auditTableBody');
const q           = document.getElementById('q');
const outcomeSel  = document.getElementById('outcome');
const chips       = [...document.querySelectorAll('.chip')];
const resultCount = document.getElementById('resultCount');
const prevPage    = document.getElementById('prevPage');
const nextPage    = document.getElementById('nextPage');
const pageInfo    = document.getElementById('pageInfo');
const exportBtn   = document.getElementById('exportBtn');
const clearBtn    = document.getElementById('clearBtn');
const headers     = [...document.querySelectorAll('thead th')];

// --- State ---
let DATA = [];
let RULES_BY_TITLE = new Map(); // title -> { rule_id, cc_sfr, severity }
let RULES_BY_ID    = new Map(); // rule_id -> { rule_id, cc_sfr, severity }
let sortKey = 'priority'; // default: Failed → Severity → Control
let sortDir = 'desc';
let page = 1;
const pageSize = 12;
const activeCats = new Set();

// --- API helper ---
const api = (window.occt && window.occt.api)
  ? window.occt.api
  : (p => '/api/sample' + p);

// --- Utils ---
const escapeHTML = (s='') =>
  String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));

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

const badge = cat => {
  const cls = cat === 'System' ? 'sys' : cat === 'Security' ? 'sec' : 'acc';
  return `<span class="badge ${cls}">${escapeHTML(cat || '')}</span>`;
};
const outcomePill = o =>
  `<span class="outcome ${String(o).toLowerCase() === 'passed' ? 'pass' : 'fail'}">${escapeHTML(o || '')}</span>`;

const sevRank = s => ({ critical:4, high:3, medium:2, low:1 }[String(s||'').toLowerCase()] || 0);
const outRank = o => ({ failed:2, fail:2, passed:1, pass:1 }[String(o||'').toLowerCase()] || 0);

function severityPill(key) {
  const k = (key || '').toLowerCase();
  const label = k ? k.charAt(0).toUpperCase() + k.slice(1) : '—';
  return `<span class="pill sev-${k || 'na'}">${escapeHTML(label)}</span>`;
}

const rowSev = (r) => {
  const meta = RULES_BY_TITLE.get((r.control || r.title || '').trim()) || RULES_BY_ID.get((r.rule_id || '').trim()) || {};
  return sevRank(r.severity || meta.severity);
};

const tableColspan = () => (headers.length || 9); // robust if headers already updated

// --- Fetch + normalize ---
async function loadData() {
  tbody.innerHTML = `<tr><td colspan="${tableColspan()}">Loading…</td></tr>`;
  try {
    const [resAudit, resRules] = await Promise.all([
      fetch(api('/audit')),
      fetch(api('/rules')).catch(() => ({ ok:false }))
    ]);
    if (!resAudit.ok) throw new Error('HTTP ' + resAudit.status);

    const json = await resAudit.json();
    DATA = (Array.isArray(json) ? json : []).map(r => ({
      time:        r.time || r.timestamp || null,
      category:    r.category || '',
      control:     r.control || r.check_name || '',
      outcome:     r.outcome || r.status || '',
      account:     r.account || r.host || '',
      description: r.description || '',
      // NOTE: 'code' previously used by you for misc tags; keep it for back-compat search/export
      code:        r.code || r.cc || r.cc_id || '',
      // If backend ever sends these, we’ll honor them; otherwise we compute from RULES maps.
      rule_id:     r.rule_id || '',     // optional
      cc_sfr:      r.cc_sfr  || '',     // optional
      severity:    r.severity || ''     // optional
    }));

    if (resRules && resRules.ok) {
      const list = await resRules.json();
      RULES_BY_TITLE = new Map();
      RULES_BY_ID    = new Map();
      if (Array.isArray(list)) {
        list.forEach(x => {
          const item = {
            rule_id: (x.id || '').trim(),
            cc_sfr:  (x.cc_sfr || '').trim(),
            severity: (x.severity || '').toLowerCase()
          };
          const titleKey = (x.title || x.id || '').trim();
          if (titleKey) RULES_BY_TITLE.set(titleKey, item);
          if (item.rule_id) RULES_BY_ID.set(item.rule_id, item);
        });
      }
    } else {
      RULES_BY_TITLE = new Map();
      RULES_BY_ID    = new Map();
    }
  } catch (err) {
    console.error('Audit load failed:', err);
    DATA = [];
    tbody.innerHTML = `<tr><td colspan="${tableColspan()}">Failed to load audit data.</td></tr>`;
  }
}

// --- Resolve meta for a row (uses both maps + row fallbacks) ---
function metaForRow(r) {
  const titleKey = (r.control || '').trim();
  const byTitle  = RULES_BY_TITLE.get(titleKey);
  // Prefer explicit row.rule_id (if ever provided) otherwise ID from title match
  const rid = (r.rule_id || (byTitle && byTitle.rule_id) || '').trim();
  const byId = rid ? RULES_BY_ID.get(rid) : null;

  const rule_id = rid || (byId && byId.rule_id) || (byTitle && byTitle.rule_id) || '';
  const cc_sfr  = (r.cc_sfr || (byId && byId.cc_sfr) || (byTitle && byTitle.cc_sfr) || '');
  const severity = (r.severity || (byId && byId.severity) || (byTitle && byTitle.severity) || '');

  return { rule_id, cc_sfr, severity };
}

// --- Filter + Sort ---
function filtered() {
  const text = (q?.value || '').trim().toLowerCase();
  const oc   = outcomeSel?.value || '';

  const rows = DATA.filter(r => {
    if (activeCats.size && !activeCats.has(r.category)) return false;
    if (oc && r.outcome !== oc) return false;

    if (text) {
      const m = metaForRow(r);
      const hay = `${r.description} ${r.control} ${r.account} ${r.category} ${r.code} ${m.rule_id} ${m.cc_sfr}`.toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });

  if (sortKey === 'priority') {
    rows.sort((a,b) => {
      const oc = outRank(b.outcome) - outRank(a.outcome); if (oc) return oc;
      const sc = rowSev(b) - rowSev(a);                   if (sc) return sc;
      const an = (a.control || '').toLowerCase();
      const bn = (b.control || '').toLowerCase();
      return an.localeCompare(bn);
    });
    return rows;
  }

  const dir = (sortDir === 'asc') ? 1 : -1;

  if (sortKey === 'rule_id' || sortKey === 'cc_sfr') {
    return rows.sort((a,b) => {
      const am = metaForRow(a), bm = metaForRow(b);
      const av = (sortKey === 'rule_id' ? (am.rule_id || '') : (am.cc_sfr || '')).toLowerCase();
      const bv = (sortKey === 'rule_id' ? (bm.rule_id || '') : (bm.cc_sfr || '')).toLowerCase();
      return av.localeCompare(bv) * dir;
    });
  }

  if (sortKey === 'severity') {
    return rows.sort((a,b) => {
      const av = sevRank((metaForRow(a).severity || '').toLowerCase());
      const bv = sevRank((metaForRow(b).severity || '').toLowerCase());
      return (av - bv) * dir;
    });
  }

  // Fallbacks (time/category/control/outcome/account/etc.)
  return rows.sort((a,b) => {
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
  const slice = rows.slice((page - 1) * pageSize, (page - 1) * pageSize + pageSize);

  if (!slice.length) {
    tbody.innerHTML = `<tr><td colspan="${tableColspan()}">No results.</td></tr>`;
  } else {
    tbody.innerHTML = slice.map(r => {
      const m = metaForRow(r);
      return `
        <tr data-cat="${escapeHTML(r.category || '')}">
          <td>${fmtTime(r.time)}</td>
          <td>${badge(r.category)}</td>
          <td class="cell-wrap">${escapeHTML(r.control)}</td>
          <td class="cell-nw">${escapeHTML(m.rule_id || '—')}</td>
          <td class="cell-nw">${escapeHTML(m.cc_sfr  || '—')}</td>
          <td class="cell-nw">${severityPill(m.severity)}</td>
          <td>${outcomePill(r.outcome)}</td>
          <td class="cell-nw">${escapeHTML(r.account)}</td>
          <td class="cell-wrap">
            ${escapeHTML(r.description)}
            ${r.code ? `<div class="code-line">${escapeHTML(r.code)}</div>` : ''}
          </td>
        </tr>
      `;
    }).join('');
  }

  if (pageInfo) pageInfo.textContent = `${page} / ${totalPages}`;
  if (prevPage) prevPage.disabled = page <= 1;
  if (nextPage) nextPage.disabled = page >= totalPages;
}

// --- Events ---
if (q) q.addEventListener('input', () => { page = 1; render(); });
if (outcomeSel) outcomeSel.addEventListener('change', () => { page = 1; render(); });

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
    if (key === 'priority') {
      sortKey = 'priority';
      render();
      return;
    }
    if (sortKey === key) sortDir = (sortDir === 'asc' ? 'desc' : 'asc');
    else { sortKey = key; sortDir = key === 'time' ? 'desc' : 'asc'; }
    render();
  });
});

if (clearBtn) clearBtn.addEventListener('click', () => {
  if (q) q.value = '';
  if (outcomeSel) outcomeSel.value = '';
  activeCats.clear(); chips.forEach(c => c.classList.remove('active'));
  page = 1; render();
});

if (exportBtn) exportBtn.addEventListener('click', () => {
  const rows = filtered();
  const header = ['Time','Category','Control','Control ID','CC SFR','Severity','Outcome','Account/Host','Description','Code'];
  const csv = [header.join(',')].concat(
    rows.map(r => {
      const m = metaForRow(r);
      return [
        r.time ? new Date(r.time).toISOString() : '',
        r.category,
        (r.control || '').replaceAll('"','""'),
        (m.rule_id || '').replaceAll('"','""'),
        (m.cc_sfr  || '').replaceAll('"','""'),
        String(m.severity || '').replaceAll('"','""'),
        r.outcome,
        (r.account || '').replaceAll('"','""'),
        (r.description || '').replaceAll('"','""'),
        (r.code || '').replaceAll('"','""')
      ].map(x => `"${x}"`).join(',');
    })
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
