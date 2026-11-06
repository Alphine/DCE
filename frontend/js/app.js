// Bootstrap: session check, app shell (nav, role chip, logout), hash routes with role guards.
import { api, onUnauthenticated, ApiError } from './api.js';
import { createRouter, go } from './router.js';
import { hasRole } from './session.js';
import { toast } from './components/toast.js';
import { h, errorState } from './dom.js';

const ROUTES = [
  { name: 'login', title: 'Sign in', match: (p) => (p[0] === 'login' ? {} : null), load: () => import('./views/login.js') },
  { name: 'command', title: 'Command Center', minRole: 'Viewer',
    match: (p) => (p.length === 0 || p[0] === 'dashboard' ? {} : null), load: () => import('./views/command-center.js') },
  { name: 'datasets', title: 'Datasets', minRole: 'Viewer',
    match: (p) => (p[0] === 'datasets' ? { id: p[1] || null } : null), load: () => import('./views/datasets.js') },
  { name: 'agent', title: 'Agent', minRole: 'Analyst',
    match: (p) => (p[0] === 'agent' ? {} : null), load: () => import('./views/agent.js') },
  { name: 'task', title: 'Task', minRole: 'Viewer',
    match: (p) => (p[0] === 'tasks' && p[1] ? { id: p[1] } : null), load: () => import('./views/task.js') },
  { name: 'artifacts', title: 'Artifacts', minRole: 'Viewer',
    match: (p) => (p[0] === 'artifacts' ? {} : null), load: () => import('./views/artifacts.js') },
  { name: 'audit', title: 'Audit', minRole: 'Reviewer',
    match: (p) => (p[0] === 'audit' ? {} : null), load: () => import('./views/audit.js') },
  { name: 'about', title: 'Architecture', minRole: 'Viewer',
    match: (p) => (p[0] === 'about' ? {} : null), load: () => import('./views/about.js') },
  { name: 'notfound', title: 'Not found', match: () => null, load: null },
];

const NAV = [
  { route: 'command', label: 'Command Center', href: '#/', minRole: 'Viewer' },
  { route: 'datasets', label: 'Datasets', href: '#/datasets', minRole: 'Viewer' },
  { route: 'agent', label: 'Agent', href: '#/agent', minRole: 'Analyst' },
  { route: 'artifacts', label: 'Artifacts', href: '#/artifacts', minRole: 'Viewer' },
  { route: 'audit', label: 'Audit', href: '#/audit', minRole: 'Reviewer' },
  { route: 'about', label: 'Architecture', href: '#/about', minRole: 'Viewer' },
];

const $ = (id) => document.getElementById(id);
const main = $('view');
const topbar = $('topbar');
const nav = $('nav');
const roleChip = $('role-chip');
const usernameEl = $('username');
const logoutBtn = $('logout');

const state = { user: null };
let booting = true;
let routeToken = 0;
const active = { controller: null, cleanup: null };

function teardown() {
  if (active.controller) active.controller.abort();
  const fn = active.cleanup;
  active.controller = null;
  active.cleanup = null;
  if (typeof fn === 'function') {
    try {
      fn();
    } catch {
      // Cleanup must never block navigation.
    }
  }
}

function renderChrome(routeName) {
  topbar.hidden = !state.user;
  if (!state.user) return;
  roleChip.textContent = state.user.role;
  usernameEl.textContent = state.user.username;
  nav.replaceChildren(...NAV.filter((item) => hasRole(state.user, item.minRole)).map((item) =>
    h('a', { href: item.href, 'aria-current': item.route === routeName ? 'page' : undefined }, item.label)));
}

function forbidden(route) {
  return h('section', { class: 'state-msg empty', role: 'alert', style: 'padding-top:64px' },
    h('strong', null, 'Not available for your role'),
    h('span', null, `This screen needs the ${route.minRole} role or higher. You are signed in as ${state.user.role}.`),
    h('a', { href: '#/' }, 'Back to Command Center'));
}

function notFound() {
  return h('section', { class: 'state-msg empty', style: 'padding-top:64px' },
    h('strong', null, 'Page not found'),
    h('a', { href: '#/' }, 'Back to Command Center'));
}

async function onRoute({ route, params }) {
  const token = ++routeToken;
  teardown();

  if (!state.user && route.name !== 'login') return go('#/login');
  if (state.user && route.name === 'login') return go('#/');

  renderChrome(route.name);
  document.title = `${route.title} · Disaster Commander Edge`;
  main.replaceChildren();

  if (!route.load) return main.append(notFound());
  if (route.minRole && !hasRole(state.user, route.minRole)) return main.append(forbidden(route));

  const controller = new AbortController();
  active.controller = controller;
  try {
    const mod = await route.load();
    if (token !== routeToken) return;
    const ctx = {
      user: state.user,
      params,
      signal: controller.signal,
      navigate: go,
      toast,
      onLogin,
    };
    const cleanup = await mod.mount(main, ctx);
    if (token !== routeToken) {
      if (typeof cleanup === 'function') cleanup();
      return;
    }
    active.cleanup = typeof cleanup === 'function' ? cleanup : null;
    main.focus({ preventScroll: true });
  } catch (err) {
    if (token !== routeToken || controller.signal.aborted || err.name === 'AbortError') return;
    main.replaceChildren(errorState(err, () => go(window.location.hash || '#/')));
  }
}

async function onLogin() {
  state.user = await api.get('auth/me');
  go('#/');
}

// Session expired or missing: leave the current screen and show the login page.
onUnauthenticated(() => {
  if (booting || !state.user) return;
  state.user = null;
  toast('Your session has ended. Sign in again.', { kind: 'error' });
  go('#/login');
});

logoutBtn.addEventListener('click', async () => {
  logoutBtn.disabled = true;
  try {
    await api.postEmpty('auth/logout', { suppressAuthEvent: true });
  } catch (err) {
    // An expired session is already logged out. Anything else is shown to the user.
    if (!(err instanceof ApiError && err.code === 'UNAUTHENTICATED')) {
      toast(err.message, { kind: 'error' });
      logoutBtn.disabled = false;
      return;
    }
  }
  state.user = null;
  logoutBtn.disabled = false;
  teardown();
  go('#/login');
  renderChrome('login');
  toast('Signed out.', { kind: 'success', timeout: 2500 });
});

const router = createRouter(ROUTES, onRoute);

async function boot() {
  try {
    state.user = await api.get('auth/me');
  } catch (err) {
    state.user = null;
    if (!(err instanceof ApiError && err.code === 'UNAUTHENTICATED')) toast(err.message, { kind: 'error' });
  } finally {
    booting = false;
  }
  router.start();
}

window.addEventListener('unhandledrejection', (event) => {
  // Show the server or client message only. Never show stack traces.
  const message = event.reason && event.reason.message;
  if (message) toast(message, { kind: 'error' });
  event.preventDefault();
});

boot();
