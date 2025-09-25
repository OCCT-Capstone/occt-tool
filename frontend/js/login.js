// frontend/js/login.js
(function () {
  const form   = document.getElementById('loginForm');
  const btn    = document.getElementById('loginBtn');
  const err    = document.getElementById('err');
  const status = document.getElementById('loginStatus');

  function showError(msg) {
    if (!err) return;
    err.textContent = msg || 'Invalid username or password';
    err.style.display = 'block';
  }
  function clearError() {
    if (!err) return;
    err.textContent = '';
    err.style.display = 'none';
  }
  function setLoading(on, label) {
    if (!btn) return;
    if (on) {
      btn.classList.add('loading');
      btn.setAttribute('disabled', 'true');
      const l = btn.querySelector('.btn-label');
      if (l) l.textContent = label || 'Signing in';
      if (status) status.textContent = label || 'Signing in…';
    } else {
      btn.classList.remove('loading');
      btn.removeAttribute('disabled');
      const l = btn.querySelector('.btn-label');
      if (l) l.textContent = 'Sign in';
      if (status) status.textContent = '';
    }
  }
  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    if (!btn || btn.hasAttribute('disabled')) return;

    setLoading(true, 'Signing in…');
    const minHold = wait(600); // avoid flicker

    const username = (document.getElementById('username')?.value || '').trim();
    const password = (document.getElementById('password')?.value || '');

    try {
      // 1) Auth
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-OCCT-No-Loader': '1' }, // no global overlay on login
        body: JSON.stringify({ username, password })
      });

      if (res.status === 401) {
        await minHold;
        setLoading(false);
        return showError('Invalid username or password');
      }
      if (!res.ok) {
        await minHold;
        setLoading(false);
        return showError(`Login failed (HTTP ${res.status})`);
      }

      // 2) Optional: kick live rescan (kept from your current flow)
      try {
        if (window.occt && window.occt.loading && window.occt.loading.show) {
          window.occt.loading.show(); // only shows if loader.js is present (safe guard)
        }
        await fetch('/api/live/rescan?wait=1', { method: 'POST' });
      } catch (_) {
        // ignore — still proceed to dashboard
      } finally {
        if (window.occt && window.occt.loading && window.occt.loading.hide) {
          window.occt.loading.hide();
        }
      }

      await minHold;
      window.location.replace('/'); // dashboard shells quickly; widgets hydrate there
    } catch (ex) {
      await minHold;
      setLoading(false);
      showError('Network error. Please try again.');
    }
  });
})();
