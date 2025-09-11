// Remediation page: splits audit rows into Failed / Passed and shows hints.
(async () => {
  const api = (window.occt && window.occt.api) ? window.occt.api : (p => '/api/sample' + p);

  // Map controls -> plain-text remediation hints
  const HINTS = {
    "Minimum password length":
      "Set the minimum password length to ≥14 via GPO: Computer Configuration → Windows Settings → Security Settings → Account Policies → Password Policy.",
    "Password complexity":
      "Enable “Password must meet complexity requirements” in the same Password Policy GPO. Apply to all user scopes.",
    "Dormant account disable":
      "Find inactive accounts (e.g., lastLogonTimestamp > 90 days) and disable or remove. Review with ADUC or a scheduled script.",
    "Service hardening":
      "Remove/disable unnecessary services (e.g., Telnet). Example: `sc stop tlntsvr` and `sc config tlntsvr start= disabled`. Review via services.msc.",
    "Firewall enabled":
      "Ensure Windows Defender Firewall is ON for Domain/Private/Public via GPO: Windows Defender Firewall with Advanced Security → Windows Firewall Properties.",
    "MFA enforced":
      "Require MFA for admins via your IdP (e.g., Entra ID Conditional Access → Grant → Require MFA). Ensure at least two registered methods.",
    "SMB signing required":
      "Enable “Digitally sign communications (always)” for client and server via GPO: Security Options → Microsoft network client/server."
  };

  // Fallback per category
  const CAT_HINT = {
    "System":  "Harden the host via GPO/baselines. Apply least functionality and disable unused services.",
    "Security":"Align with password/audit/policy baselines. Enforce via GPO and verify with auditpol.",
    "Account":"Apply least privilege. Regularly review privileged groups and disable stale accounts."
  };

  const badgeClass = (cat) => cat === 'System' ? 'sys' : (cat === 'Security' ? 'sec' : 'acc');
  const esc = (s='') => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  // Unified AU formatter for this page as well
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

  const hintFor = (control, category) => HINTS[control] || CAT_HINT[category] || "Review the expected value and apply the required configuration. Document the change.";

  try {
    const res = await fetch(api('/audit'));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const rows = await res.json();

    const failed = rows.filter(r => r.outcome === 'Failed');
    const passed = rows.filter(r => r.outcome === 'Passed');

    const fixList = document.getElementById('fixList');
    const okList  = document.getElementById('okList');

    // Render helpers
    function render(listEl, data, state){
      if (!data.length){
        listEl.innerHTML = `<div class="empty">${state === 'fail' ? 'No failed checks 🎉' : 'No compliant items yet.'}</div>`;
        return;
      }
      listEl.innerHTML = data.map(r => `
        <article class="fix ${state}">
          <div class="head">
            <div class="title">${esc(r.control || r.title || 'Untitled control')}</div>
            <span class="badge ${badgeClass(r.category || '')}">${esc(r.category || '')}</span>
          </div>
          <div class="meta">
            ${r.account ? `<span>Account/Host: <strong>${esc(r.account)}</strong></span>` : ''}
            ${r.time ? `<span>${esc(fmtTime(r.time))}</span>` : ''}
            <span>Outcome: <strong>${esc(r.outcome || '')}</strong></span>
          </div>
          <p class="hint">${esc(hintFor(r.control, r.category))}</p>
          ${r.description ? `<p class="muted" style="margin-top:.25rem;">Observed: ${esc(r.description)}</p>` : ''}
        </article>
      `).join('');
    }

    render(fixList, failed, 'fail');
    render(okList,  passed, 'pass');

  } catch (e) {
    console.error('Remediation load failed:', e);
    document.getElementById('fixList').innerHTML = `<div class="empty">Couldn’t load audit data.</div>`;
    document.getElementById('okList').innerHTML  = '';
  }
})();
