// frontend/js/remediation.js

(async () => {
  const api = (window.occt && window.occt.api) ? window.occt.api : (p => '/api/sample' + p);

  const FALLBACK_CAT_HINT = {
    "System":  "Harden the host using Microsoft security baselines. Disable unused services and apply least functionality.",
    "Security":"Align password/audit policies with your baseline. Enforce via GPO and verify with 'auditpol'.",
    "Account":"Apply least privilege. Review privileged groups regularly and disable or remove stale accounts."
  };

  const esc = (s='') =>
    String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const badgeClass = (cat) => cat === 'System' ? 'sys' : (cat === 'Security' ? 'sec' : 'acc');

  const fmtTime = (iso) => {
    if (!iso) return '';
    if (window.occt && typeof window.occt.formatDateTimeAU === 'function') {
      return window.occt.formatDateTimeAU(iso);
    }
    const d = new Date(iso);
    return d.toLocaleString('en-AU', {
      timeZone: 'Australia/Sydney',
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).replace(',', '');
  };

  function splitObservedRemediation(desc) {
    if (!desc) return { observed: '', remediation: '' };
    const marker = 'Remediation:';
    const i = desc.indexOf(marker);
    if (i >= 0) {
      const observed = desc.slice(0, i).replace(/\|\s*$/, '').trim();
      const remediation = desc.slice(i + marker.length).trim();
      return { observed, remediation };
    }
    return { observed: desc.trim(), remediation: '' };
  }


  function cleanRemediationText(hintRaw) {
    if (!hintRaw) return '';
    let s = String(hintRaw);
    s = s.replace(/\bundefined\b/g, '');
    s = s.replace(/\s{2,}/g, ' ').trim();
    return s;
  }

  async function fetchAudit() {
    const res = await fetch(api('/audit'));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  async function fetchRulesMap() {
    try {
      const res = await fetch(api('/rules'));
      if (!res.ok) return new Map();
      const list = await res.json();
      return new Map(list.map(r => [ (r.title || r.id || '').trim(), { remediation: r.remediation || '', severity: (r.severity || '').toLowerCase() } ]));
    } catch {
      return new Map();
    }
  }

  function chooseRemediation(row, rulesMap) {
    const { remediation } = splitObservedRemediation(row.description || '');
    if (remediation) return remediation;
    const key = (row.control || row.title || '').trim();
    const fromRule = rulesMap.get(key)?.remediation;
    if (fromRule) return fromRule;
    return FALLBACK_CAT_HINT[row.category] || 'Review the observed value and apply the required configuration.';
  }

  const sevRank = s => ({ high:3, medium:2, low:1 }[String(s||'').toLowerCase()] || 0);
  const rowSev = (r, rulesMap) => {
    const key = (r.control || r.title || '').trim();
    const raw = r.severity || rulesMap.get(key)?.severity;
    return sevRank(raw);
  };

  try {
    const [rows, rulesMap] = await Promise.all([fetchAudit(), fetchRulesMap()]);

    const failed = rows
      .filter(r => (r.outcome || '').toLowerCase() === 'failed')

      .sort((a,b) => {
        const sc = rowSev(b, rulesMap) - rowSev(a, rulesMap); if (sc) return sc;
        const an = (a.control || '').toLowerCase();
        const bn = (b.control || '').toLowerCase();
        return an.localeCompare(bn);
      });

    const passed = rows
      .filter(r => (r.outcome || '').toLowerCase() === 'passed')
      .sort((a,b) => {
        const an = (a.control || '').toLowerCase();
        const bn = (b.control || '').toLowerCase();
        return an.localeCompare(bn);
      });

    const fixList = document.getElementById('fixList');
    const okList  = document.getElementById('okList');

    function render(listEl, data, state){
      if (!listEl) return;
      if (!data.length){
        listEl.innerHTML = `<div class="empty">${state === 'fail' ? 'No failed checks 🎉' : 'No compliant items yet.'}</div>`;
        return;
      }
      listEl.innerHTML = data.map(r => {
        const { observed } = splitObservedRemediation(r.description || '');
        const hintRaw = state === 'fail' ? chooseRemediation(r, rulesMap) : '';
        const hint = cleanRemediationText(hintRaw);
        const host = r.account || r.host || '';

        return `
          <article class="fix ${state}">
            <div class="head">
              <div class="title">${esc(r.control || r.title || 'Untitled control')}</div>
              <span class="badge ${badgeClass(r.category || '')}">${esc(r.category || '')}</span>
            </div>
            <div class="meta">
              ${host ? `<span>Host: <strong>${esc(host)}</strong></span>` : ''}
              ${r.time ? `<span>${esc(fmtTime(r.time))}</span>` : ''}
              <span>Outcome: <strong>${esc(r.outcome || '')}</strong></span>
            </div>
            ${hint ? `<p class="hint"><strong>Remediation:</strong> ${esc(hint)}</p>` : ''}
            ${observed ? `<p class="muted" style="margin-top:.25rem;"><strong>Observed:</strong> ${esc(observed)}</p>` : ''}
          </article>
        `;
      }).join('');
    }

    render(fixList, failed, 'fail');
    render(okList,  passed, 'pass');

  } catch (e) {
    console.error('Remediation load failed:', e);
    const fixList = document.getElementById('fixList');
    const okList  = document.getElementById('okList');
    if (fixList) fixList.innerHTML = `<div class="empty">Couldn’t load audit data.</div>`;
    if (okList)  okList.innerHTML  = '';
  }
})();
