// static/js/login.js
(function () {
  const form = document.getElementById('loginForm');
  const err  = document.getElementById('err');

  function showError(msg){
    if (!err) return;
    err.textContent = msg || 'Invalid username or password';
    err.style.display = 'block';
  }
  function hideError(){
    if (err) err.style.display = 'none';
  }

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();

    const username = (document.getElementById('username') || {}).value || '';
    const password = (document.getElementById('password') || {}).value || '';

    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      if (res.ok) {
        // Show loading overlay if available, run a LIVE rescan, then go to dashboard
        try {
          if (window.occt && window.occt.loading && window.occt.loading.show) {
            window.occt.loading.show();
          }
          // No opt-out header here: we WANT the overlay visible during login bootstrap
          await fetch('/api/live/rescan?wait=1', { method: 'POST' });
        } catch (_) {
          // ignore rescan errors; still continue to dashboard
        } finally {
          if (window.occt && window.occt.loading && window.occt.loading.hide) {
            window.occt.loading.hide();
          }
        }
        window.location.replace('/');
      } else if (res.status === 401) {
        showError('Invalid username or password');
      } else {
        showError(`Login failed (HTTP ${res.status})`);
      }
    } catch (err) {
      showError('Network error. Please try again.');
    }
  });
})();
