const K = window.occt.K;
const $ = (s) => document.querySelector(s);

const themeDark = $('#themeDark');
const apiMode   = $('#apiMode');
const form      = $('#settingsForm');
const toast     = $('#toast');
const resetBtn  = $('#resetBtn');
const logoutBtn = $('#logoutBtn');

const DEFAULTS = {
  [K.THEME]: 'light',
  [K.MODE]:  'sample',
};

function load() {
  const theme = localStorage.getItem(K.THEME) || DEFAULTS[K.THEME];
  const mode  = localStorage.getItem(K.MODE)  || DEFAULTS[K.MODE];

  themeDark.checked = theme === 'dark';
  apiMode.value = mode;

  // apply theme immediately
  document.documentElement.classList.toggle('theme-dark', themeDark.checked);
}

function save(e) {
  e.preventDefault();
  localStorage.setItem(K.THEME, themeDark.checked ? 'dark' : 'light');
  localStorage.setItem(K.MODE, apiMode.value);

  document.documentElement.classList.toggle('theme-dark', themeDark.checked);

  toast.hidden = false;
  toast.textContent = 'Saved';
  setTimeout(() => (toast.hidden = true), 1200);
}

function resetAll() {
  Object.entries(DEFAULTS).forEach(([k,v]) => localStorage.setItem(k, v));
  load();
  toast.hidden = false;
  toast.textContent = 'Defaults restored';
  setTimeout(() => (toast.hidden = true), 1200);
}

function logoutPlaceholder() {
  toast.hidden = false;
  toast.textContent = 'Logout not implemented yet';
  setTimeout(() => (toast.hidden = true), 1200);
}

form.addEventListener('submit', save);
resetBtn.addEventListener('click', resetAll);
logoutBtn.addEventListener('click', logoutPlaceholder);
load();
