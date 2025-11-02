// frontend/js/dashboard-alert.js
(function () {
  const occt = window.occt || { K: { MODE: 'occt.apiMode' } };
  const K = occt.K;

  function getMode() {
    try { return localStorage.getItem(K.MODE) || 'live'; } catch { return 'live'; }
  }
  function pageApi(path) {
    return (getMode() === 'sample' ? '/api/sample' : '/api/live') + path;
  }

  const STYLE_ID = 'occt-toast-style';
  const WRAP_ID  = 'occt-toast-wrap';
  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
#${WRAP_ID}{
  position: fixed; top: 16px; right: 16px; z-index: 9998; display: grid; gap: 12px;
}
.occt-toast{
  min-width: 300px; max-width: 420px;
  background: var(--surface-2, #0f172a); color: var(--text-1, #e5e7eb);
  border: 1px solid rgba(255,255,255,.12); border-left: 6px solid #ef4444; /* RED accent */
  padding: 1rem 1.1rem; border-radius: .9rem; box-shadow: 0 10px 28px rgba(0,0,0,.35);
  display: grid; grid-template-columns: 1fr auto; align-items: start; gap: .8rem;
  font-size: 1rem; line-height: 1.45;
  opacity: 0; transform: translateX(40px); /* start off-screen to the right */
  transition: transform .22s ease-out, opacity .22s ease-out;
  will-change: transform, opacity;
}
.occt-toast.show{
  opacity: 1; transform: translateX(0);
}
.occt-toast.leaving{
  opacity: 0; transform: translateX(60px);
}
.occt-toast.success { border-left-color: #10b981; }
.occt-toast .msg{ font-size: 1rem; }
.occt-toast .close{
  border: none; background: transparent; color: inherit; cursor: pointer;
  opacity: .8; font-size: 1.15rem; line-height: 1;
}
.occt-toast .close:hover{ opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  .occt-toast, .occt-toast.show, .occt-toast.leaving { transition: none; transform: none !important; opacity: 1 !important; }
}
    `.trim();
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.appendChild(document.createTextNode(css));
    document.head.appendChild(style);
  }
  function ensureWrap() {
    let el = document.getElementById(WRAP_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = WRAP_ID;
      document.body.appendChild(el);
    }
    return el;
  }

  function toast({ html, kind = 'warn', timeout = 6000 }) {
    ensureStyle();
    const wrap = ensureWrap();
    const t = document.createElement('div');
    t.className = 'occt-toast' + (kind === 'success' ? ' success' : '');
    t.innerHTML = `
      <div class="msg">${html}</div>
      <button class="close" aria-label="Close">×</button>
    `;
    wrap.appendChild(t);

    requestAnimationFrame(() => t.classList.add('show'));

    const close = () => {
      t.classList.add('leaving');
      const done = () => t.remove();
      t.addEventListener('transitionend', done, { once: true });
      setTimeout(done, 300);
    };

    t.querySelector('.close')?.addEventListener('click', close);

    if (timeout > 0) setTimeout(close, timeout);

    let startX = 0, curX = 0, dragging = false;
    const threshold = 60;
    const onDown = (e) => {
      dragging = true;
      startX = (e.touches ? e.touches[0].clientX : e.clientX);
      curX = startX;
      t.style.transition = 'none';
    };
    const onMove = (e) => {
      if (!dragging) return;
      curX = (e.touches ? e.touches[0].clientX : e.clientX);
      const dx = Math.max(0, curX - startX);
      t.style.transform = `translateX(${dx + 0}px)`;
      t.style.opacity = String(Math.max(0, 1 - dx / 160));
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      const dx = Math.max(0, curX - startX);
      t.style.transition = '';
      if (dx > threshold) close();
      else {
        t.style.transform = '';
        t.style.opacity = '';
      }
    };
    t.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: false });

    t.addEventListener('transitionend', () => {
      if (!document.body.contains(t)) {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      }
    });

    return t;
  }

  function alreadyShownFor(completedAt) {
    try {
      const key = 'occt.toast.scanShown';
      const prev = sessionStorage.getItem(key);
      if (prev === completedAt) return true;
      sessionStorage.setItem(key, completedAt || 'none');
      return false;
    } catch { return false; }
  }

  async function maybeShowComplianceToast() {
    try {
      const res = await fetch(pageApi('/last-scan'), {
        headers: { 'X-OCCT-No-Loader': '1' },
        credentials: 'include'
      });
      if (!res.ok) return;
      const j = await res.json();
      if (!j?.has_data) return;

      const completedAt  = j.completed_at || '';
      if (alreadyShownFor(completedAt)) return;

      const failed = Number(j.failed_count ?? 0);
      const passed = Number(j.passed_count ?? 0);
      const checks = Number(j.check_count ?? (passed + failed || 0));

      if (checks > 0 && failed > 0) {
        const html = `
          <strong>Warning:</strong> ${failed} check${failed===1?'':'s'} failed compliance.
          <div class="actions" style="margin-top:.45rem;">
            <button class="close btn primary" style="margin-right:.5rem">Dismiss</button>
            <button class="btn primary" onclick="location.href='/audit'">View details</button>
          </div>
        `;
        toast({ html, kind: 'warn', timeout: 7000 });
      }
    } catch {
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', maybeShowComplianceToast, { once: true });
  } else {
    maybeShowComplianceToast();
  }
})();
