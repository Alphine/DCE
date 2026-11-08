// Bootstrap: session check, app shell (nav, role chip, logout), hash routes with role guards.
import { api, onUnauthenticated, ApiError } from './api.js';
import { createRouter, go } from './router.js';
import { hasRole } from './session.js';
import { toast } from './components/toast.js';
import { h, errorState } from './dom.js';
import { icon } from './components/icons.js';
import { start as startSync, subscribe as subscribeSync, rememberUser, forgetUser, cachedUser } from './offline/sync.js';

// Routes that work without a session: sign-in, the emailed password reset, public warnings, About and the landing page.
// Public routes skip the minRole check, so a visitor (no role) can open them.
const PUBLIC_ROUTES = new Set(['login', 'reset', 'public', 'about', 'landing']);

// A visitor (not signed in) at the command route sees the landing page. Signed-in users, and the demo sandbox
// (which signs in as a demo user), keep the Command Center.
const LANDING_ROUTE = { name: 'landing', title: 'Welcome', load: () => import('./views/landing.js') };

const ROUTES = [
  { name: 'login', title: 'Sign in', match: (p) => (p[0] === 'login' ? {} : null), load: () => import('./views/login.js') },
  { name: 'reset', title: 'Reset password', match: (p) => (p[0] === 'reset' ? {} : null), load: () => import('./views/reset.js') },
  { name: 'pending', title: 'Pending', minRole: 'Viewer',
    match: (p) => (p[0] === 'pending' ? {} : null), load: () => import('./views/pending.js') },
  { name: 'command', title: 'Command Center', minRole: 'Viewer',
    match: (p) => (p.length === 0 || p[0] === 'dashboard' ? {} : null), load: () => import('./views/command-center.js') },
  { name: 'situation', title: 'Situation', minRole: 'Viewer',
    match: (p) => (p[0] === 'situation' ? {} : null), load: () => import('./views/situation.js') },
  { name: 'analysis', title: 'Hazard Intelligence', minRole: 'Viewer',
    match: (p) => (p[0] === 'analysis' ? {} : null), load: () => import('./views/hazards.js') },
  { name: 'planning', title: 'Planning', minRole: 'Viewer',
    match: (p) => (p[0] === 'planning' ? { id: p[1] || null } : null), load: () => import('./views/planning.js') },
  { name: 'resources', title: 'Resource Planner', minRole: 'Viewer',
    match: (p) => (p[0] === 'resources' ? {} : null), load: () => import('./views/resources.js') },
  { name: 'missions', title: 'Missions', minRole: 'Viewer',
    match: (p) => (p[0] === 'missions' ? { id: p[1] || null } : null), load: () => import('./views/missions.js') },
  { name: 'simulation', title: 'Simulation', minRole: 'Viewer',
    match: (p) => (p[0] === 'simulation' ? { id: p[1] || null } : null), load: () => import('./views/simulation.js') },
  { name: 'reports', title: 'Reports', minRole: 'Viewer',
    match: (p) => (p[0] === 'reports' ? { id: p[1] || null } : null), load: () => import('./views/reports.js') },
  { name: 'datasets', title: 'Datasets', minRole: 'Viewer',
    match: (p) => (p[0] === 'datasets' ? { id: p[1] || null } : null), load: () => import('./views/datasets.js') },
  { name: 'agent', title: 'Agent', minRole: 'Analyst',
    match: (p) => (p[0] === 'agent' ? {} : null), load: () => import('./views/agent.js') },
  { name: 'task', title: 'Task', minRole: 'Viewer',
    match: (p) => (p[0] === 'tasks' && p[1] ? { id: p[1] } : null), load: () => import('./views/task.js') },
  { name: 'artifacts', title: 'Artifacts', minRole: 'Viewer',
    match: (p) => (p[0] === 'artifacts' ? {} : null), load: () => import('./views/artifacts.js') },
  { name: 'public', title: 'Public warnings', match: (p) => (p[0] === 'public' ? {} : null), load: () => import('./views/public-warnings.js') },
  { name: 'alerts', title: 'Alerts', minRole: 'Viewer',
    match: (p) => (p[0] === 'alerts' ? {} : null), load: () => import('./views/alerts.js') },
  { name: 'logistics', title: 'Logistics', minRole: 'Viewer',
    match: (p) => (p[0] === 'logistics' ? {} : null), load: () => import('./views/logistics.js') },
  { name: 'admin', title: 'Users', minRole: 'Admin',
    match: (p) => (p[0] === 'admin' ? {} : null), load: () => import('./views/admin-users.js') },
  { name: 'audit', title: 'Audit', minRole: 'Reviewer',
    match: (p) => (p[0] === 'audit' ? {} : null), load: () => import('./views/audit.js') },
  { name: 'about', title: 'Architecture', minRole: 'Viewer',
    match: (p) => (p[0] === 'about' ? {} : null), load: () => import('./views/about.js') },
  { name: 'notfound', title: 'Not found', match: () => null, load: null },
];

// Primary navigation: the operating picture. Labels match the design reference.
const PRIMARY_NAV = [
  { route: 'command', label: 'Command', href: '#/', icon: 'command', minRole: 'Viewer' },
  { route: 'situation', label: 'Situation', href: '#/situation', icon: 'situation', minRole: 'Viewer' },
  { route: 'analysis', label: 'Analysis', href: '#/analysis', icon: 'analysis', minRole: 'Viewer' },
  { route: 'planning', label: 'Planning', href: '#/planning', icon: 'planning', minRole: 'Viewer' },
  { route: 'resources', label: 'Resources', href: '#/resources', icon: 'resources', minRole: 'Viewer' },
  { route: 'missions', label: 'Missions', href: '#/missions', icon: 'missions', minRole: 'Viewer' },
  { route: 'simulation', label: 'Simulation', href: '#/simulation', icon: 'simulation', minRole: 'Viewer' },
  { route: 'reports', label: 'Reports', href: '#/reports', icon: 'reports', minRole: 'Viewer' },
];

// Tools: pages that already work today. Kept visible in a second row so nothing is lost.
const TOOLS_NAV = [
  { route: 'datasets', label: 'Datasets', href: '#/datasets', icon: 'datasets', minRole: 'Viewer' },
  { route: 'agent', label: 'Agent', href: '#/agent', icon: 'agent', minRole: 'Analyst' },
  { route: 'artifacts', label: 'Artifacts', href: '#/artifacts', icon: 'artifacts', minRole: 'Viewer' },
  { route: 'audit', label: 'Audit', href: '#/audit', icon: 'audit', minRole: 'Reviewer' },
  { route: 'alerts', label: 'Alerts', href: '#/alerts', icon: 'alerts', minRole: 'Viewer' },
  { route: 'logistics', label: 'Logistics', href: '#/logistics', icon: 'logistics', minRole: 'Viewer' },
  { route: 'admin', label: 'Users', href: '#/admin', icon: 'users', minRole: 'Admin' },
  { route: 'about', label: 'Architecture', href: '#/about', icon: 'architecture', minRole: 'Viewer' },
];

const $ = (id) => document.getElementById(id);
const main = $('view');
const topbar = $('topbar');
const nav = $('nav');
const toolsNav = $('nav-tools');
const bottomNav = $('bottom-nav');
// Phone navigation: the five destinations used most in the field.
const BOTTOM_NAV = [
  PRIMARY_NAV.find((i) => i.route === 'command'),
  PRIMARY_NAV.find((i) => i.route === 'situation'),
  TOOLS_NAV.find((i) => i.route === 'alerts'),
  PRIMARY_NAV.find((i) => i.route === 'missions'),
  PRIMARY_NAV.find((i) => i.route === 'reports'),
].filter(Boolean);
const roleChip = $('role-chip');
const usernameEl = $('username');
const userEmailEl = $('user-email');
const logoutBtn = $('logout');
const connPill = $('conn-pill');
const connText = $('conn-text');
const syncLink = $('sync-status');

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

function navLinks(items, routeName, className) {
  return items.filter((item) => hasRole(state.user, item.minRole)).map((item) =>
    h('a', {
      href: item.href,
      class: className,
      'aria-current': item.route === routeName ? 'page' : undefined,
    }, icon(item.icon), h('span', { class: 'nav-label' }, item.label)));
}

function renderChrome(routeName) {
  topbar.hidden = !state.user;
  if (!state.user) return;
  roleChip.textContent = state.user.role;
  usernameEl.textContent = state.user.username;
  userEmailEl.textContent = state.user.email || 'No email set';
  userEmailEl.classList.toggle('is-empty', !state.user.email);
  nav.replaceChildren(...navLinks(PRIMARY_NAV, routeName, 'nav-item'));
  toolsNav.replaceChildren(...navLinks(TOOLS_NAV, routeName, 'nav-tool'));
  bottomNav.replaceChildren(...navLinks(BOTTOM_NAV, routeName, 'bottom-item'));
}

// Connection state. Offline when the browser is offline or the last sync request could not reach the server.
// The pending and rejected counts link to the Pending panel.
function renderConnection(status = null) {
  const online = status ? status.online : navigator.onLine !== false;
  connPill.dataset.state = online ? 'online' : 'offline';
  connText.textContent = online ? 'Online' : 'Offline';
  if (status) {
    syncLink.textContent = `${status.pending} pending · ${status.rejected} rejected`;
    syncLink.classList.toggle('has-rejected', status.rejected > 0);
    syncLink.setAttribute('aria-label', `${status.pending} pending and ${status.rejected} rejected offline changes. Open the Pending list.`);
  }
}
window.addEventListener('online', () => renderConnection());
window.addEventListener('offline', () => renderConnection());
subscribeSync((status) => renderConnection(status));

function forbidden(route) {
  return h('section', { class: 'state-msg empty state-msg--page', role: 'alert' },
    h('strong', null, 'Not available for your role'),
    h('span', null, `This screen needs the ${route.minRole} role or higher. You are signed in as ${state.user.role}.`),
    h('a', { href: '#/' }, 'Back to Command Center'));
}

function notFound() {
  return h('section', { class: 'state-msg empty state-msg--page' },
    h('strong', null, 'Page not found'),
    h('a', { href: '#/' }, 'Back to Command Center'));
}

async function onRoute({ route: matched, params }) {
  const token = ++routeToken;
  teardown();

  const route = !state.user && matched.name === 'command' ? LANDING_ROUTE : matched;

  if (!state.user && !PUBLIC_ROUTES.has(route.name)) return go('#/login');
  if (state.user && route.name === 'login') return go('#/');

  renderChrome(route.name);
  document.title = `${route.title} · Disaster Commander Edge`;
  main.replaceChildren();

  if (!route.load) return main.append(notFound());
  if (route.minRole && !PUBLIC_ROUTES.has(route.name) && !hasRole(state.user, route.minRole)) return main.append(forbidden(route));

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
  await rememberUser(state.user);
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
  await forgetUser();
  teardown();
  go('#/login');
  renderChrome('login');
  toast('Signed out.', { kind: 'success', timeout: 2500 });
});

const router = createRouter(ROUTES, onRoute);

async function boot() {
  try {
    state.user = await api.get('auth/me');
    await rememberUser(state.user);
  } catch (err) {
    state.user = null;
    if (err instanceof ApiError && err.status === 0) {
      // Offline: keep the read-only cache for the last user whose session was valid. Writes queue until sync.
      state.user = await cachedUser();
      if (!state.user) toast('You are offline and no saved session was found. Connect once to sign in.', { kind: 'error' });
    } else if (!(err instanceof ApiError && err.code === 'UNAUTHENTICATED')) {
      toast(err.message, { kind: 'error' });
    }
  } finally {
    booting = false;
  }
  startSync();
  router.start();
}

window.addEventListener('unhandledrejection', (event) => {
  // Show the server or client message only. Never show stack traces.
  const message = event.reason && event.reason.message;
  if (message) toast(message, { kind: 'error' });
  event.preventDefault();
});

boot();
