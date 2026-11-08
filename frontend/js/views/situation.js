import { api } from '../api.js';
import { h, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import {
  createLeafletMap, filterPoints, countryCodes, normalizeCountry, layerForPoint, isMappable, LAYERS,
} from '../components/leaflet-map.js';
import { toNumber } from '../domain.js';

// Situation picture. Verified field reports with coordinates, rows with lat and lon from approved datasets,
// and shelters when the logistics endpoint exists. The server decides what is included; this view only draws
// and lists what it returns. The map and the table always show the same filtered points.

const LIMIT = 500;
export const KIND_LABEL = { REPORT: 'Verified report', DATASET_ROW: 'Dataset row', SHELTER: 'Shelter' };

// Returns true only for coordinates the map can place.
export function isValidCoord(lat, lon) {
  return lat !== null && lon !== null && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

// Normalises one situation point. lat and lon are null when the coordinates are unusable: the table still
// lists such a point, and the map skips it.
export function toSituationPoint(p, index = 0) {
  if (!p) return null;
  const kind = String(p.kind || 'POINT');
  const lat = toNumber(p.lat);
  const lon = toNumber(p.lon);
  const ok = isValidCoord(lat, lon);
  const isReport = kind === 'REPORT';
  const details = isReport
    ? [{ label: 'Status', value: p.status || '—' }, { label: 'Data class', value: p.data_class || '—' }]
    : [{ label: 'Dataset', value: p.dataset_name || '—' }, { label: 'Row', value: p.row ?? '—' }];
  return {
    id: `${kind}:${p.id ?? index}`,
    kind,
    label: String(p.label || 'Unnamed point'),
    lat: ok ? lat : null,
    lon: ok ? lon : null,
    severity: toNumber(p.severity),
    country_code: normalizeCountry(p.country_code),
    data_class: p.data_class ? String(p.data_class) : null,
    layer: layerForPoint({ kind }),
    type: isReport ? (p.hazard || p.hazard_type || KIND_LABEL.REPORT) : (KIND_LABEL[kind] || KIND_LABEL.DATASET_ROW),
    details,
  };
}

// Kept for callers that want only drawable points. Returns null when coordinates are unusable.
export function toMapPoint(p) {
  const point = toSituationPoint(p);
  return point && isValidCoord(point.lat, point.lon) ? point : null;
}

// Shelter rows from GET /api/logistics/shelters. Field names are read defensively.
export function toShelterPoint(s, index = 0) {
  if (!s) return null;
  // The registry returns latitude, longitude and capacity_people (see backend/app/routes/logistics.py).
  const lat = toNumber(s.latitude ?? s.lat);
  const lon = toNumber(s.longitude ?? s.lon);
  const ok = isValidCoord(lat, lon);
  return {
    id: `SHELTER:${s.id ?? index}`,
    kind: 'SHELTER',
    label: String(s.name || s.label || 'Unnamed shelter'),
    lat: ok ? lat : null,
    lon: ok ? lon : null,
    severity: null,
    country_code: normalizeCountry(s.country_code),
    data_class: null,
    layer: 'shelters',
    type: KIND_LABEL.SHELTER,
    details: [{ label: 'Capacity', value: s.capacity_people ?? s.capacity ?? '—' }, { label: 'Status', value: s.status || '—' }],
  };
}

// Display text for a coordinate. Missing or non-numeric values show a dash.
export function coordText(value) {
  const n = toNumber(value);
  return n === null ? '—' : n.toFixed(4);
}

export function countKind(points, kind) {
  return points.filter((p) => p && p.kind === kind).length;
}

// Shelters: { available, failed, points }. A 404 means the endpoint does not exist yet, so the layer is hidden.
async function fetchShelters(signal) {
  try {
    const data = await api.get('logistics/shelters', { signal });
    const rows = Array.isArray(data) ? data
      : Array.isArray(data && data.shelters) ? data.shelters
        : listOf(data);
    return { available: true, failed: false, points: rows.map((s, i) => toShelterPoint(s, i)).filter(Boolean) };
  } catch (err) {
    if (err && err.status === 404) return { available: false, failed: false, points: [] };
    return { available: true, failed: true, points: [] };
  }
}

export async function mount(root, ctx) {
  const { signal } = ctx;
  const state = {
    layers: { disaster: true, shelters: true, affected: true, countries: true },
    country: null,
    all: [],
    shelterLayer: false,
  };
  const summary = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const noteSlot = h('div', { 'aria-live': 'polite' });
  const controlSlot = h('div', { class: 'situation-controls' });
  const mapSlot = h('div', { class: 'situation-map' });
  const detailSlot = h('div');
  const listNote = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const tableSlot = h('div', null, spinner('Loading points…'));
  let map = null;
  let mapToken = 0;

  root.append(
    pageHead('Situation',
      'Verified field reports with coordinates, rows with lat and lon from approved datasets, and shelters when available.'),
    panel({ title: 'Map', sub: 'Select a point on the map or in the table for its details. The layer and country controls filter both.', style: '--i:1' },
      summary, noteSlot, controlSlot, mapSlot, detailSlot),
    panel({ title: 'Points', sub: 'The points shown on the map, in the order the server sent them.', style: '--i:2' },
      listNote, tableSlot));

  async function load() {
    tableSlot.replaceChildren(spinner('Loading points…'));
    try {
      const [data, shelters] = await Promise.all([
        api.get('situation', { query: { limit: LIMIT }, signal }),
        fetchShelters(signal),
      ]);
      if (signal.aborted) return;
      render(data || {}, shelters);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      tableSlot.replaceChildren(errorState(err, load));
    }
  }

  function render(data, shelters) {
    const situation = listOf(data.points).map((p, i) => toSituationPoint(p, i)).filter(Boolean);
    state.all = [...situation, ...shelters.points];
    state.shelterLayer = shelters.available;
    const counts = data.counts || {};
    const reports = Number.isFinite(counts.REPORT) ? counts.REPORT : countKind(situation, 'REPORT');
    const rows = Number.isFinite(counts.DATASET_ROW) ? counts.DATASET_ROW : countKind(situation, 'DATASET_ROW');
    const shelterText = shelters.available ? ` · ${shelters.points.length} shelters` : '';
    summary.textContent = `${reports} verified reports · ${rows} dataset rows${shelterText}`;
    const notes = [];
    if (data.truncated) notes.push(alertBox('info', `Only the first ${LIMIT} points are listed. More exist in the data.`));
    if (shelters.failed) notes.push(alertBox('warn', 'Shelter data could not be loaded. The shelter layer is empty.'));
    noteSlot.replaceChildren(...notes);
    detailSlot.replaceChildren();

    if (!state.all.length) {
      destroyMap();
      controlSlot.replaceChildren();
      mapSlot.replaceChildren();
      listNote.textContent = '';
      tableSlot.replaceChildren(emptyState('No points yet',
        'Verified reports with coordinates and approved dataset rows with lat and lon appear here.'));
      return;
    }
    renderControls();
    renderTable();
    mountMap();
  }

  // Builds the layer checkboxes and the country select from the current points.
  function renderControls() {
    const codes = countryCodes(state.all);
    if (state.country && !codes.includes(state.country)) state.country = null;

    const select = h('select', { id: 'situation-country', class: 'situation-country' },
      h('option', { value: '' }, 'All countries'),
      codes.map((c) => h('option', { value: c }, c)));
    select.value = state.country || '';
    select.disabled = codes.length === 0;
    select.addEventListener('change', () => setCountry(select.value || null));
    const countryHint = codes.length
      ? `${codes.length} country code(s) on the points.`
      : 'No point carries a country code yet, so the country filter is off.';

    const layerDefs = [
      ['disaster', 'Disaster points'],
      ...(state.shelterLayer ? [['shelters', 'Shelters']] : []),
      ['affected', 'Affected areas'],
      ['countries', 'Country outlines'],
    ];
    const checks = layerDefs.map(([id, text]) => {
      const input = h('input', { type: 'checkbox', id: `situation-layer-${id}`, value: id });
      input.checked = state.layers[id] !== false;
      input.addEventListener('change', () => setLayer(id, input.checked));
      return h('label', { class: 'situation-layer', for: `situation-layer-${id}` }, input, ` ${text}`);
    });

    controlSlot.replaceChildren(
      h('div', { class: 'field' },
        h('label', { class: 'label', for: 'situation-country' }, 'Country'),
        select,
        h('p', { class: 'hint' }, countryHint)),
      h('fieldset', { class: 'situation-layers' },
        h('legend', { class: 'label' }, 'Layers'),
        checks));
  }

  function visibleRows() {
    return filterPoints(state.all, { layers: state.layers, country: state.country });
  }

  function setLayer(id, on) {
    state.layers[id] = on;
    if (map) map.setLayer(id, on);
    renderTable();
  }

  function setCountry(code) {
    state.country = normalizeCountry(code);
    if (map) map.setCountry(state.country);
    renderTable();
  }

  // The map is optional: if it fails, the table below still lists every point.
  async function mountMap() {
    destroyMap();
    const token = ++mapToken;
    const drawable = state.all.filter(isMappable);
    mapSlot.replaceChildren();
    if (!drawable.length) {
      mapSlot.append(emptyState('Nothing to draw', 'None of these points has usable coordinates. The table still lists them.'));
      return;
    }
    mapSlot.append(h('p', { class: 'small muted' }, 'Loading map…'));
    try {
      const ctrl = await createLeafletMap(mapSlot, {
        points: drawable,
        layers: state.layers,
        country: state.country,
        onSelect: showDetail,
        label: 'Situation map of verified reports, dataset rows and shelters. The table below lists the same points.',
      });
      if (token !== mapToken || signal.aborted) {
        ctrl.destroy();
        return;
      }
      map = ctrl;
      map.setPoints(drawable);
    } catch {
      if (token !== mapToken) return;
      mapSlot.replaceChildren(alertBox('warn', 'The map could not be drawn. The table below still lists every point.'));
    }
  }

  function destroyMap() {
    mapToken += 1;
    if (map) map.destroy();
    map = null;
  }

  function showDetail(point) {
    if (!point) {
      detailSlot.replaceChildren();
      return;
    }
    detailSlot.replaceChildren(h('div', { class: 'situation-detail' },
      h('h3', { class: 'panel-title' }, 'Selected point'),
      h('dl', { class: 'kv-list' },
        kv('Point', point.label),
        kv('Kind', point.type || LAYERS[point.layer]?.label || '—'),
        kv('Coordinates', `${coordText(point.lat)}, ${coordText(point.lon)}`),
        kv('Country', point.country_code || '—'),
        ...(point.details || []).map((line) => kv(line.label, line.value))),
      h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => clearSelection() }, 'Clear selection')));
  }

  function clearSelection() {
    if (map) map.clearSelection();
    else showDetail(null);
  }

  // Choosing a row selects the same point on the map, so keyboard users reach every point.
  function choose(point) {
    if (map) {
      map.select(point.id);
      mapSlot.scrollIntoView?.({ block: 'nearest' });
    } else {
      showDetail(point);
    }
  }

  function renderTable() {
    const rows = visibleRows();
    listNote.textContent = `Showing ${rows.length} of ${state.all.length} points.`;
    if (!rows.length) {
      tableSlot.replaceChildren(emptyState('No points match', 'Change the country or layer controls to see more points.'));
      return;
    }
    tableSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Points on the situation map, after the layer and country filters'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Kind'),
          h('th', { scope: 'col' }, 'Label'),
          h('th', { scope: 'col' }, 'Country'),
          h('th', { scope: 'col', class: 'num' }, 'Latitude'),
          h('th', { scope: 'col', class: 'num' }, 'Longitude'),
          h('th', { scope: 'col' }, 'Data class'))),
        h('tbody', null, rows.map(pointRow)))));
  }

  function pointRow(p) {
    const drawable = isMappable(p);
    const labelCell = drawable
      ? h('button', { class: 'btn btn-link', type: 'button', onclick: () => choose(p) }, p.label)
      : h('span', null, p.label, ' ', h('span', { class: 'muted' }, '(no coordinates)'));
    return h('tr', { 'data-id': p.id },
      h('td', null, KIND_LABEL[p.kind] || String(p.kind || '—')),
      h('td', { class: 'wrap-any' }, labelCell),
      h('td', null, p.country_code || '—'),
      h('td', { class: 'num mono' }, coordText(p.lat)),
      h('td', { class: 'num mono' }, coordText(p.lon)),
      h('td', null, p.data_class ? dataClassBadge(p.data_class) : '—'));
  }

  await load();
  return () => destroyMap();
}
