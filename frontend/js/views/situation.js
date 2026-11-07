import { api } from '../api.js';
import { h, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { createWorldMap, pointDescription } from '../components/world-map.js';
import { toNumber } from '../domain.js';

// Situation picture. Verified field reports with coordinates, and rows with lat and lon from approved
// datasets. The server decides what is included; this view only draws and lists what it returns.
// Every point keeps its data class. Map circles cover both kinds, so the map has one layer.

const LIMIT = 500;
export const KIND_LABEL = { REPORT: 'Verified report', DATASET_ROW: 'Dataset row' };

// Returns true only for coordinates the map can place.
export function isValidCoord(lat, lon) {
  return lat !== null && lon !== null && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

// Turns one API point into the shape createWorldMap expects. Returns null when coordinates are unusable.
export function toMapPoint(p) {
  if (!p) return null;
  const lat = toNumber(p.lat);
  const lon = toNumber(p.lon);
  if (!isValidCoord(lat, lon)) return null;
  const isReport = p.kind === 'REPORT';
  const details = isReport
    ? [{ label: 'Status', value: p.status || '—' }, { label: 'Data class', value: p.data_class || '—' }]
    : [{ label: 'Dataset', value: p.dataset_name || '—' }, { label: 'Row', value: p.row ?? '—' }];
  return {
    label: String(p.label || 'Unnamed point'),
    lat,
    lon,
    layer: 'disaster',
    type: isReport ? (p.hazard || p.hazard_type || KIND_LABEL.REPORT) : KIND_LABEL.DATASET_ROW,
    details,
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

export async function mount(root, ctx) {
  const { signal } = ctx;
  const summary = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const noteSlot = h('div', { 'aria-live': 'polite' });
  const mapSlot = h('div', { class: 'situation-map' });
  const detailSlot = h('div');
  const tableSlot = h('div', null, spinner('Loading points…'));
  let map = null;

  root.append(
    pageHead('Situation',
      'Verified field reports with coordinates, and rows with lat and lon from approved datasets. Each point keeps its data class.'),
    panel({ title: 'Map', sub: 'Select a circle for its details. Arrow keys move between points, Escape clears the selection.', style: '--i:1' },
      summary, noteSlot, mapSlot, detailSlot),
    panel({ title: 'Points', sub: 'Every point returned by the server, in the order it sent them.', style: '--i:2' }, tableSlot));

  async function load() {
    tableSlot.replaceChildren(spinner('Loading points…'));
    try {
      const data = await api.get('situation', { query: { limit: LIMIT }, signal });
      if (signal.aborted) return;
      render(data || {});
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      tableSlot.replaceChildren(errorState(err, load));
    }
  }

  function render(data) {
    const points = listOf(data.points);
    const counts = data.counts || {};
    const reports = Number.isFinite(counts.REPORT) ? counts.REPORT : countKind(points, 'REPORT');
    const rows = Number.isFinite(counts.DATASET_ROW) ? counts.DATASET_ROW : countKind(points, 'DATASET_ROW');
    summary.textContent = `${reports} verified reports · ${rows} dataset rows`;
    noteSlot.replaceChildren(data.truncated ? alertBox('info', `Only the first ${LIMIT} points are listed. More exist in the data.`) : null);
    detailSlot.replaceChildren();

    if (!points.length) {
      destroyMap();
      mapSlot.replaceChildren();
      tableSlot.replaceChildren(emptyState('No points yet',
        'Verified reports with coordinates and approved dataset rows with lat and lon appear here.'));
      return;
    }
    mountMap(points.map(toMapPoint).filter(Boolean));
    tableSlot.replaceChildren(pointTable(points));
  }

  // The map is optional: if it fails, the table below still lists every point.
  function mountMap(mapPoints) {
    destroyMap();
    mapSlot.replaceChildren();
    if (!mapPoints.length) {
      mapSlot.append(emptyState('Nothing to draw', 'None of these points has usable coordinates. The table still lists them.'));
      return;
    }
    try {
      map = createWorldMap(mapSlot, { points: mapPoints, onSelect: showDetail });
      if (map.skipped.length) {
        noteSlot.append(alertBox('info', `${map.skipped.length} point(s) lie outside the drawn map. They appear in the table only.`));
      }
    } catch {
      map = null;
      mapSlot.replaceChildren(alertBox('warn', 'The map could not be drawn. The table below still lists every point.'));
    }
  }

  function destroyMap() {
    if (map) map.destroy();
    map = null;
  }

  function showDetail(point) {
    if (!point) {
      detailSlot.replaceChildren();
      return;
    }
    const d = pointDescription(point);
    detailSlot.replaceChildren(h('div', { class: 'situation-detail' },
      h('h3', { class: 'panel-title' }, 'Selected point'),
      h('dl', { class: 'kv-list' },
        kv('Point', point.label),
        kv('Kind', point.type || d.layerLabel),
        kv('Coordinates', d.coords),
        ...(point.details || []).map((line) => kv(line.label, line.value)))));
  }

  function pointTable(points) {
    return h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Points on the situation map'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Kind'),
          h('th', { scope: 'col' }, 'Label'),
          h('th', { scope: 'col', class: 'num' }, 'Latitude'),
          h('th', { scope: 'col', class: 'num' }, 'Longitude'),
          h('th', { scope: 'col' }, 'Data class'))),
        h('tbody', null, points.map(pointRow))));
  }

  function pointRow(p) {
    return h('tr', null,
      h('td', null, KIND_LABEL[p.kind] || String(p.kind || '—')),
      h('td', { class: 'wrap-any' }, p.label || '—'),
      h('td', { class: 'num mono' }, coordText(p.lat)),
      h('td', { class: 'num mono' }, coordText(p.lon)),
      h('td', null, p.data_class ? dataClassBadge(String(p.data_class)) : '—'));
  }

  await load();
  return () => destroyMap();
}
