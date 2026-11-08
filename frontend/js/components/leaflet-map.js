// Leaflet command map for the Situation screen.
// Leaflet 1.9.4 is vendored under frontend/vendor/leaflet and the country outlines are Natural Earth 110m
// admin-0 countries under frontend/data/geo. Both are same-origin, so the map works offline once the
// service worker has cached them. There is no tile layer: the background is plain, so no tile server is contacted.
//
// Points: { id, lat, lon, kind, label, severity?, country_code?, layer?, type?, details?: [{label, value}] }
// The kind decides the layer: REPORT and DATASET_ROW are "disaster", SHELTER is "shelters", AFFECTED is "affected".
// Labels and details are always set as text nodes. Nothing from the data goes through innerHTML.
//
// Pure helpers (filterPoints, countryCodes, layerForPoint, normalizeCountry, isMappable) have no DOM access,
// so they can be tested in Node.

export const LAYERS = Object.freeze({
  disaster: Object.freeze({ id: 'disaster', label: 'Disaster points', color: '#ffb020' }),
  shelters: Object.freeze({ id: 'shelters', label: 'Shelters', color: '#3fd8f0' }),
  affected: Object.freeze({ id: 'affected', label: 'Affected areas', color: '#ff4d62' }),
  countries: Object.freeze({ id: 'countries', label: 'Country outlines', color: '#8a9ab8' }),
});

const POINT_LAYERS = Object.freeze(['disaster', 'shelters', 'affected']);
const LAYER_BY_KIND = Object.freeze({ REPORT: 'disaster', DATASET_ROW: 'disaster', SHELTER: 'shelters', AFFECTED: 'affected' });
export const DEFAULT_LAYERS = Object.freeze({ disaster: true, shelters: true, affected: true, countries: true });

const LEAFLET_CSS = new URL('../../vendor/leaflet/leaflet.css', import.meta.url).href;
const LEAFLET_JS = new URL('../../vendor/leaflet/leaflet.js', import.meta.url).href;
const COUNTRIES_URL = new URL('../../data/geo/countries-110m.geojson', import.meta.url).href;
const WORLD_CENTER = [15, 110];
const WORLD_ZOOM = 2;

// ---- Pure helpers ----

// The layer a point is drawn on. An explicit known point layer wins; otherwise the kind decides.
export function layerForPoint(p) {
  if (p && POINT_LAYERS.includes(p.layer)) return p.layer;
  return (p && LAYER_BY_KIND[p.kind]) || 'disaster';
}

// True only for coordinates the map can place.
export function isMappable(p) {
  return !!p && Number.isFinite(p.lat) && Number.isFinite(p.lon)
    && p.lat >= -90 && p.lat <= 90 && p.lon >= -180 && p.lon <= 180;
}

// ISO 3166-1 alpha-2 code in upper case, or null when the value is not one.
export function normalizeCountry(code) {
  if (typeof code !== 'string') return null;
  const c = code.trim().toUpperCase();
  return /^[A-Z]{2}$/.test(c) ? c : null;
}

// Keeps the points whose layer is switched on. When a country is given, keeps only points whose
// country_code matches it. Points without a country_code never match a country filter.
export function filterPoints(points, { layers, country } = {}) {
  const on = { ...DEFAULT_LAYERS, ...(layers || {}) };
  const wanted = normalizeCountry(country);
  return (Array.isArray(points) ? points : []).filter((p) => {
    if (!p) return false;
    if (on[layerForPoint(p)] === false) return false;
    return !wanted || normalizeCountry(p.country_code) === wanted;
  });
}

// Sorted, unique country codes found on the points.
export function countryCodes(points) {
  const codes = new Set();
  for (const p of Array.isArray(points) ? points : []) {
    const code = normalizeCountry(p && p.country_code);
    if (code) codes.add(code);
  }
  return [...codes].sort();
}

// ---- Browser loading ----

// Element creation with text-only children. Strings become text nodes.
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children) {
    if (child === undefined || child === null || child === false) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
}

let leafletReady = null;
// Adds the vendored stylesheet and script once per page. Resolves to the global L.
export function loadLeaflet() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('The map needs a browser'));
  }
  if (window.L) return Promise.resolve(window.L);
  if (!leafletReady) {
    if (!document.querySelector('link[data-leaflet]')) {
      const link = el('link', { rel: 'stylesheet', href: LEAFLET_CSS, 'data-leaflet': true });
      document.head.append(link);
    }
    leafletReady = new Promise((resolve, reject) => {
      const script = el('script', { src: LEAFLET_JS });
      script.onload = () => (window.L ? resolve(window.L) : reject(new Error('Leaflet did not start')));
      script.onerror = () => {
        script.remove();
        reject(new Error('Leaflet could not be loaded'));
      };
      document.head.append(script);
    }).catch((err) => {
      leafletReady = null;
      throw err;
    });
  }
  return leafletReady;
}

let countriesReady = null;
// Country outlines are fetched once per page and shared by every map.
export function loadCountries() {
  if (!countriesReady) {
    countriesReady = fetch(COUNTRIES_URL, { credentials: 'same-origin' })
      .then((res) => {
        if (!res.ok) throw new Error(`Country outlines returned HTTP ${res.status}`);
        return res.json();
      })
      .catch((err) => {
        countriesReady = null;
        throw err;
      });
  }
  return countriesReady;
}

function reduceMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function radiusFor(p) {
  const s = Number(p.severity);
  return Number.isFinite(s) ? Math.min(12, Math.max(6, 5 + s)) : 7;
}

function markerStyle(p, selected) {
  const meta = LAYERS[layerForPoint(p)];
  return {
    radius: radiusFor(p),
    color: selected ? '#ffffff' : meta.color,
    fillColor: meta.color,
    fillOpacity: 0.85,
    weight: selected ? 3 : 1.5,
  };
}

function outlineStyle(selected) {
  return selected
    ? { color: '#ffb020', weight: 2, fillColor: '#2a2a18', fillOpacity: 0.9 }
    : { color: '#4b5a7a', weight: 0.6, fillColor: '#16203a', fillOpacity: 1 };
}

function tooltipElement(p, layerId) {
  return el('span', { class: 'lm-tip' },
    el('strong', null, String(p.label || 'Unnamed point')),
    ` · ${LAYERS[layerId].label}`);
}

// Creates the map inside container. Resolves to a controller:
//   select(id) / clearSelection(): highlight a point; onSelect(point | null) is called.
//   setLayer(name, on), setCountry(code | null), setPoints(points), destroy().
// Rejects when Leaflet or the outlines cannot start; the caller should then show its table only.
// Outlines that fail to load do not reject: the points still show and a note appears.
export async function createLeafletMap(container, { points = [], layers = {}, country = null, onSelect, label = 'Map' } = {}) {
  const [L, outlineData] = await Promise.all([
    loadLeaflet(),
    loadCountries().catch(() => null),
  ]);

  const visible = { ...DEFAULT_LAYERS, ...layers };
  const state = {
    points: (Array.isArray(points) ? points : []).filter(isMappable),
    country: normalizeCountry(country),
    selectedId: null,
  };
  let destroyed = false;

  const root = el('div', { class: 'lm', role: 'region', 'aria-label': label });
  if (!outlineData) {
    root.append(el('p', { class: 'lm-note small', role: 'status' }, 'Country outlines could not be loaded. The points still show.'));
  }
  const mapEl = el('div', { class: 'lm-map' });
  root.append(mapEl);
  container.replaceChildren(root);

  const map = L.map(mapEl, {
    minZoom: 1,
    maxZoom: 10,
    worldCopyJump: true,
    zoomAnimation: !reduceMotion(),
  }).setView(WORLD_CENTER, WORLD_ZOOM);
  map.attributionControl.addAttribution('Countries: Natural Earth (public domain)');

  const countryLayer = L.geoJSON(outlineData || { type: 'FeatureCollection', features: [] }, {
    style: () => outlineStyle(false),
    interactive: false,
  });
  const pointGroups = { disaster: L.layerGroup(), shelters: L.layerGroup(), affected: L.layerGroup() };
  const groups = { countries: countryLayer, ...pointGroups };
  for (const id of Object.keys(groups)) {
    if (visible[id] !== false) groups[id].addTo(map);
  }

  const markers = new Map(); // id -> { point, marker }

  function paintOutlines() {
    countryLayer.eachLayer((layer) => {
      const iso = normalizeCountry(layer.feature && layer.feature.properties && layer.feature.properties.iso2);
      layer.setStyle(outlineStyle(!!iso && iso === state.country));
    });
  }

  function findOutline(code) {
    return countryLayer.getLayers().find((layer) => {
      const iso = normalizeCountry(layer.feature && layer.feature.properties && layer.feature.properties.iso2);
      return iso === code;
    }) || null;
  }

  function fitView() {
    if (state.country) {
      const outline = findOutline(state.country);
      if (outline) {
        map.fitBounds(outline.getBounds(), { padding: [16, 16], maxZoom: 6 });
        return;
      }
    }
    const shown = filterPoints(state.points, { country: state.country });
    if (shown.length) {
      map.fitBounds(L.latLngBounds(shown.map((p) => [p.lat, p.lon])), { padding: [24, 24], maxZoom: 6 });
      return;
    }
    map.setView(WORLD_CENTER, WORLD_ZOOM);
  }

  function drawPoints() {
    for (const group of Object.values(pointGroups)) group.clearLayers();
    markers.clear();
    for (const p of filterPoints(state.points, { country: state.country })) {
      const id = String(p.id);
      const layerId = layerForPoint(p);
      const selected = id === state.selectedId;
      const marker = L.circleMarker([p.lat, p.lon], markerStyle(p, selected));
      marker.bindTooltip(tooltipElement(p, layerId));
      const text = `${p.label || 'Unnamed point'}, ${LAYERS[layerId].label}`;
      marker.on('add', () => {
        const node = marker.getElement && marker.getElement();
        if (node) node.setAttribute('aria-label', text);
      });
      marker.on('click', () => select(id));
      pointGroups[layerId].addLayer(marker);
      markers.set(id, { point: p, marker });
    }
    if (state.selectedId !== null && !markers.has(state.selectedId)) {
      state.selectedId = null;
      if (typeof onSelect === 'function') onSelect(null);
    }
  }

  function styleMarker(id, selected) {
    const entry = markers.get(id);
    if (!entry) return;
    entry.marker.setStyle(markerStyle(entry.point, selected));
    if (selected) entry.marker.bringToFront();
  }

  function select(id) {
    if (destroyed) return null;
    const key = id === null || id === undefined ? null : String(id);
    const entry = key !== null ? markers.get(key) : null;
    const hidden = entry && visible[layerForPoint(entry.point)] === false;
    const previous = state.selectedId;
    if (previous !== null) styleMarker(previous, false);
    if (!entry || hidden) {
      state.selectedId = null;
      if (typeof onSelect === 'function') onSelect(null);
      return null;
    }
    state.selectedId = key;
    styleMarker(key, true);
    if (typeof onSelect === 'function') onSelect(entry.point);
    return entry.point;
  }

  function setLayer(name, on) {
    if (destroyed || !(name in groups)) return false;
    visible[name] = !!on;
    const group = groups[name];
    if (visible[name]) {
      if (!map.hasLayer(group)) group.addTo(map);
    } else if (map.hasLayer(group)) {
      map.removeLayer(group);
    }
    if (!visible[name] && state.selectedId !== null) {
      const entry = markers.get(state.selectedId);
      if (entry && layerForPoint(entry.point) === name) select(null);
    }
    return visible[name];
  }

  function setCountry(code) {
    if (destroyed) return;
    state.country = normalizeCountry(code);
    drawPoints();
    paintOutlines();
    fitView();
  }

  function setPoints(next) {
    if (destroyed) return;
    state.points = (Array.isArray(next) ? next : []).filter(isMappable);
    drawPoints();
    fitView();
  }

  drawPoints();
  paintOutlines();
  fitView();

  return {
    map,
    select,
    clearSelection: () => select(null),
    setLayer,
    setCountry,
    setPoints,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      markers.clear();
      map.remove();
      root.remove();
    },
  };
}
