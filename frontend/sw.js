// Service worker for Disaster Commander Edge.
//   - App shell (every file under frontend/ that the app needs): cache-first, precached on install.
//   - Cross-origin fonts and the Chart.js CDN script: cache-first, stored when first fetched.
//   - GET /api/* list endpoints (reports, missions, datasets, simulations): network-first. If the network fails,
//     the page is asked for the saved snapshot (postMessage with a MessageChannel) and that is returned.
//   - Other GET /api/* requests: network only. If the network fails, a 503 UNAVAILABLE error is returned.
//   - /api/auth/* and every non-GET request are never cached and never intercepted.
// Bump CACHE_VERSION whenever a file in SHELL changes. Old caches are removed on activate.

const CACHE_VERSION = 'dce-shell-v11';
const SHELL_CACHE = CACHE_VERSION;
const SNAPSHOT_SECTIONS = ['reports', 'missions', 'datasets', 'simulations'];
const SNAPSHOT_TIMEOUT_MS = 2000;

// Relative to the service worker scope (the app root). Keep this list in step with the files the app imports.
const SHELL = [
  './',
  'index.html',
  'manifest.webmanifest',
  'css/app.css',
  'assets/favicon.svg',
  'assets/logo.svg',
  'icons/icon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'js/api.js',
  'js/app.js',
  'js/dom.js',
  'js/domain.js',
  'js/router.js',
  'js/session.js',
  'js/components/badges.js',
  'js/components/chart.js',
  'js/components/copy.js',
  'js/components/countries.js',
  'js/components/geo.js',
  'js/components/hash.js',
  'js/components/icons.js',
  'js/components/log-terminal.js',
  'js/components/stepper.js',
  'js/components/toast.js',
  'js/components/world-map.js',
  'js/offline/db.js',
  'js/offline/outbox.js',
  'js/offline/read-cache.js',
  'js/offline/sync.js',
  'js/views/about.js',
  'js/views/admin-users.js',
  'js/views/agent.js',
  'js/views/artifacts.js',
  'js/views/audit.js',
  'js/views/command-center.js',
  'js/views/datasets.js',
  'js/views/hazards.js',
  'js/views/login.js',
  'js/views/missions.js',
  'js/views/pending.js',
  'js/views/planning.js',
  'js/views/reports.js',
  'js/views/reset.js',
  'js/views/resources.js',
  'js/views/simulation.js',
  'js/views/situation.js',
  'js/views/task.js',
  'js/views/alerts.js',
  'js/views/logistics.js',
  'js/views/public-warnings.js',
  'js/components/decision-queue.js',
  'js/components/lang-switch.js',
  'js/components/leaflet-map.js',
  'js/components/timeseries.js',
  'js/sw-register.js',
  'js/components/mini-charts.js',
  'js/components/empty-state.js',
  'css/command.css',
  'css/charts.css',
  'css/empty.css',
  'css/polish.css',
  'css/analysis.css',
  'css/datasets.css',
  'css/runs.css',
  'js/i18n/index.js',
  'js/i18n/en.js',
  'js/i18n/id.js',
  'data/geo/countries-110m.geojson',
  'vendor/leaflet/leaflet.js',
  'vendor/leaflet/leaflet.css',
  'vendor/leaflet/LICENSE',
  'vendor/leaflet/images/layers.png',
  'vendor/leaflet/images/layers-2x.png',
  'vendor/leaflet/images/marker-icon.png',
  'vendor/leaflet/images/marker-icon-2x.png',
  'vendor/leaflet/images/marker-shadow.png',
];

// Loaded from a CDN. A no-cors request is stored as an opaque response, which is enough for a script.
const CROSS_ORIGIN_SHELL = [
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js',
];

const scopeUrl = (path) => new URL(path, self.registration.scope).toString();

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await cache.addAll(SHELL.map(scopeUrl));
    await Promise.all(CROSS_ORIGIN_SHELL.map(async (url) => {
      try {
        const res = await fetch(new Request(url, { mode: 'no-cors' }));
        if (res.ok || res.type === 'opaque') await cache.put(url, res);
      } catch {
        // Offline during install: the CDN script is fetched again on first use.
      }
    }));
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name !== SHELL_CACHE).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

// The page asks for an update to take over now. Nothing else triggers skipWaiting.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...extra },
  });
}

function unavailable() {
  return json({ error: { code: 'UNAVAILABLE', message: 'You are offline and no saved data is available for this screen.' } }, 503);
}

// Asks each open window for its saved snapshot of one list section. The page answers with
// {items, saved_at} or null. Returns null when nobody answers in time.
async function snapshotFromPage(section) {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const client of windows) {
    const reply = await new Promise((resolve) => {
      const channel = new MessageChannel();
      const finish = (value) => {
        clearTimeout(timer);
        channel.port1.close();
        resolve(value);
      };
      const timer = setTimeout(() => finish(null), SNAPSHOT_TIMEOUT_MS);
      channel.port1.onmessage = (event) => finish(event.data || null);
      client.postMessage({ type: 'SNAPSHOT_REQUEST', section }, [channel.port2]);
    });
    if (reply && Array.isArray(reply.items)) return reply;
  }
  return null;
}

async function networkFirstList(request, section) {
  try {
    return await fetch(request);
  } catch {
    const snapshot = await snapshotFromPage(section);
    if (snapshot) return json({ items: snapshot.items, saved_at: snapshot.saved_at, from_snapshot: true });
    return unavailable();
  }
}

async function networkOnlyApi(request) {
  try {
    return await fetch(request);
  } catch {
    return unavailable();
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  try {
    const res = await fetch(request);
    if (res.ok || res.type === 'opaque') cache.put(request, res.clone()).catch(() => {});
    return res;
  } catch (err) {
    // Offline navigation falls back to the shell page.
    if (request.mode === 'navigate') {
      const shell = await cache.match(scopeUrl('index.html'));
      if (shell) return shell;
    }
    throw err;
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    // Fonts and the chart script. Requests from the page carry their own mode, so only plain GETs are handled here.
    if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com' || CROSS_ORIGIN_SHELL.includes(url.href)) {
      event.respondWith(cacheFirst(request));
    }
    return;
  }

  const scope = new URL(self.registration.scope).pathname;
  const path = url.pathname.startsWith(scope) ? url.pathname.slice(scope.length) : url.pathname.replace(/^\//, '');

  if (path.startsWith('api/')) {
    const api = path.slice(4);
    if (api.startsWith('auth/')) return; // Sessions are never cached or answered from cache.
    const section = SNAPSHOT_SECTIONS.find((s) => api === s);
    if (section) event.respondWith(networkFirstList(request, section));
    else event.respondWith(networkOnlyApi(request));
    return;
  }

  event.respondWith(cacheFirst(request));
});
