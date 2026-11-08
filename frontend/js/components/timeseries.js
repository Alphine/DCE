// Hourly report intake as an inline SVG line chart, with a table fallback for screen readers and for anyone
// who wants the exact numbers. Built with createElementNS and h(); server data is only ever set as text.
import { h } from '../dom.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const W = 720;
const H = 220;
const PAD = { top: 14, right: 14, bottom: 34, left: 44 };
const SERIES = [
  { key: 'reports', label: 'All reports', cls: 'ts-line--reports' },
  { key: 'verified', label: 'Verified', cls: 'ts-line--verified' },
];

let seq = 0;

function svgEl(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

// "2026-11-08T17:00:00Z" -> "11-08 17:00" (UTC; the label says so)
function shortHour(iso) {
  return typeof iso === 'string' && iso.length >= 16 ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : String(iso);
}

function validBuckets(data) {
  const list = data && Array.isArray(data.buckets) ? data.buckets : [];
  return list.filter((b) => b && typeof b.hour === 'string');
}

// data: the /api/timeseries response, { buckets: [{hour, reports, verified, by_hazard}] }.
export function timeseriesChart(data, { title = 'Report intake per hour (UTC)' } = {}) {
  const buckets = validBuckets(data);
  if (buckets.length === 0) {
    return h('p', { class: 'small muted', role: 'status' }, 'No time series data for this window.');
  }

  const id = `ts-title-${++seq}`;
  const n = buckets.length;
  const maxY = Math.max(1, ...buckets.flatMap((b) => [Number(b.reports) || 0, Number(b.verified) || 0]));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const xAt = (i) => PAD.left + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (v) => PAD.top + innerH - ((Number(v) || 0) / maxY) * innerH;

  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'ts-svg', role: 'img', 'aria-labelledby': id });
  svg.append(svgEl('title', { id }, `${title}. ${n} hourly buckets. Table below has the values.`));

  // Horizontal grid and y labels: 0, half, max.
  for (const frac of [0, 0.5, 1]) {
    const value = Math.round(maxY * frac);
    const y = yAt(value);
    svg.append(svgEl('line', { x1: PAD.left, x2: W - PAD.right, y1: y, y2: y, class: 'ts-grid' }));
    svg.append(svgEl('text', { x: PAD.left - 8, y: y + 4, class: 'ts-axis', 'text-anchor': 'end' }, String(value)));
  }

  // X labels: about six, always including the first and last bucket.
  const step = Math.max(1, Math.ceil(n / 6));
  buckets.forEach((b, i) => {
    if (i % step !== 0 && i !== n - 1) return;
    svg.append(svgEl('text', {
      x: xAt(i), y: H - 10, class: 'ts-axis',
      'text-anchor': i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle',
    }, shortHour(b.hour)));
  });

  for (const series of SERIES) {
    const points = buckets.map((b, i) => `${xAt(i).toFixed(1)},${yAt(b[series.key]).toFixed(1)}`).join(' ');
    svg.append(svgEl('polyline', { points, class: `ts-line ${series.cls}`, fill: 'none' }));
    if (n <= 48) {
      buckets.forEach((b, i) => {
        svg.append(svgEl('circle', { cx: xAt(i), cy: yAt(b[series.key]), r: 2.5, class: `ts-dot ${series.cls}` }));
      });
    }
  }

  const legend = h('ul', { class: 'ts-legend' },
    SERIES.map((s) => h('li', null, h('span', { class: `ts-swatch ${s.cls}`, 'aria-hidden': 'true' }), s.label)));

  const table = h('table', { class: 'table' },
    h('caption', { class: 'sr-only' }, `${title}, one row per hour`),
    h('thead', null, h('tr', null,
      h('th', { scope: 'col' }, 'Hour (UTC)'),
      h('th', { scope: 'col', class: 'num' }, 'All reports'),
      h('th', { scope: 'col', class: 'num' }, 'Verified'))),
    h('tbody', null, buckets.map((b) => h('tr', null,
      h('td', { class: 'mono' }, shortHour(b.hour)),
      h('td', { class: 'num' }, String(b.reports ?? 0)),
      h('td', { class: 'num' }, String(b.verified ?? 0))))));

  return h('figure', { class: 'ts' },
    h('div', { class: 'ts-frame' }, svg),
    legend,
    h('details', { class: 'ts-table' },
      h('summary', null, 'Show as table'),
      h('div', { class: 'table-wrap' }, table)));
}
