// Hash router. Routes look like "#/tasks/{id}" or "#/datasets/{id}". Query strings after "?" are allowed.

export function parseHash(hash = window.location.hash) {
  const raw = hash.replace(/^#/, '').replace(/^\/+/, '');
  const [path, query = ''] = raw.split('?');
  const parts = path
    .split('/')
    .filter(Boolean)
    .map((part) => {
      try {
        return decodeURIComponent(part);
      } catch {
        return part;
      }
    });
  return { parts, query: new URLSearchParams(query) };
}

export function go(path) {
  const target = path.startsWith('#') ? path : `#${path}`;
  if (window.location.hash === target) {
    // Same hash: no hashchange event fires, so re-dispatch manually.
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}

// routes: [{ name, match(parts) -> params | null, ... }]
export function createRouter(routes, onRoute) {
  function resolve() {
    const { parts } = parseHash();
    for (const route of routes) {
      const params = route.match(parts);
      if (params) return { route, params };
    }
    return { route: routes.find((r) => r.name === 'notfound'), params: {} };
  }
  function start() {
    window.addEventListener('hashchange', () => onRoute(resolve()));
    onRoute(resolve());
  }
  return { start, resolve };
}
