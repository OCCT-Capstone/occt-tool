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
        // Go to dashboard on success
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
