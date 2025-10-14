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

    if (!username || !password) {
      setLoading(false);
      return showError('Please enter username and password');
    }

    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-OCCT-No-Loader': '1' },
        body: JSON.stringify({ username, password })
      });

      if (res.status === 401) {
        await minHold; setLoading(false);
        return showError('Invalid username or password');
      }
      if (!res.ok) {
        await minHold; setLoading(false);
        return showError(`Login failed (HTTP ${res.status})`);
      }

      const data = await res.json();
      await minHold;

      // Redirect only (no scan here)
      window.location.replace(data.redirect || '/home');

    } catch {
      await minHold; setLoading(false);
      showError('Network error. Please try again.');
    }
  });
})();
