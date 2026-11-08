// Small charts for operator screens: sparklines, labelled bar rows, coverage gauges and a table fallback.
// Pure helpers (num, clamp, barShare, barShares, gaugeState, coveragePercent, sparklinePoints) take plain
// numbers and have no DOM use, so they can be tested in Node. Builders use createElementNS for SVG and h()
// for HTML, and set server data only as text. Nothing here uses innerHTML.
import { h } from '../dom.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
export const TONES = Object.freeze(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);
const TONE_CLASS = { LOW: 'sev-low', MEDIUM: 'sev-medium', HIGH: 'sev-high', CRITICAL: 'sev-critical' };

// ---- pure helpers -------------------------------------------------------------------------------

// Finite number, or NaN. null, undefined, blank strings and non-numeric values give NaN.
export function num(value) {
  if (value === null || value === undefined) return NaN;
  if (typeof value === 'string' && value.trim() === '') return NaN;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : NaN;
}

export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

// Severity tone name (LOW, MEDIUM, HIGH, CRITICAL, any case) to its CSS class. Unknown tones give ''.
export function toneClass(tone) {
  const key = typeof tone === 'string' ? tone.trim().toUpperCase() : '';
  return Object.prototype.hasOwnProperty.call(TONE_CLASS, key) ? TONE_CLASS[key] : '';
}

// Share of max as 0..1. A missing or non-positive max, or a NaN value, gives 0.
export function barShare(value, max) {
  const v = num(value);
  const m = num(max);
  if (Number.isNaN(v) || Number.isNaN(m) || m <= 0) return 0;
  return clamp(v / m, 0, 1);
}

// Each value as a share of the largest one, 0..1. Non-finite and negative values count as 0.
export function barShares(values) {
  const list = nonNegative(values);
  const top = Math.max(0, ...list);
  return list.map((v) => (top > 0 ? v / top : 0));
}

// Percent clamped to 0..100. NaN or missing input counts as 0 and hasData is false.
export function gaugeState(percent) {
  const n = num(percent);
  if (Number.isNaN(n)) return { value: 0, hasData: false };
  return { value: clamp(n, 0, 100), hasData: true };
}

// Stock as a percent of need. Missing stock or need gives NaN. Need of 0 is fully covered (100).
export function coveragePercent(stock, need) {
  const s = num(stock);
  const d = num(need);
  if (Number.isNaN(s) || Number.isNaN(d) || d < 0) return NaN;
  if (d === 0) return 100;
  return (s / d) * 100;
}

// Values as plotted: non-finite and negative values are drawn at zero.
function nonNegative(values) {
  const list = Array.isArray(values) ? values : [];
  return list.map((v) => {
    const n = num(v);
    return Number.isNaN(n) || n < 0 ? 0 : n;
  });
}

// Point coordinates for a sparkline. The scale runs from 0 to the largest value, so an empty or
// all-zero series sits on the baseline. A single value is drawn in the middle.
export function sparklinePoints(values, { width = 160, height = 40, pad = 2 } = {}) {
  const list = nonNegative(values);
  const n = list.length;
  if (n === 0) return [];
  const top = Math.max(...list);
  const innerW = Math.max(0, width - 2 * pad);
  const innerH = Math.max(0, height - 2 * pad);
  return list.map((v, i) => ({
    x: n === 1 ? width / 2 : pad + (i / (n - 1)) * innerW,
    y: top > 0 ? pad + innerH - (v / top) * innerH : pad + innerH,
  }));
}

export function pointsAttr(points) {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
}

// Count or quantity for display: grouped digits, or "no data".
export function fmtNum(value) {
  const n = num(value);
  return Number.isNaN(n) ? 'no data' : n.toLocaleString();
}

// ---- DOM builders -------------------------------------------------------------------------------

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function joinClass(...parts) {
  return parts.filter(Boolean).join(' ');
}

function sparkLabel(label, values) {
  const list = Array.isArray(values) ? values : [];
  const finite = list.map(num).filter((n) => !Number.isNaN(n));
  if (finite.length === 0) return `${label}: no data`;
  const latest = num(list[list.length - 1]);
  const peak = Math.max(...finite);
  const latestText = Number.isNaN(latest) ? 'no data' : fmtNum(latest);
  return `${label}: ${finite.length} values, latest ${latestText}, peak ${fmtNum(peak)}`;
}

// Inline SVG line over the values. Scale starts at zero. The aria-label gives the count, latest and peak.
export function sparkline(values, { width = 160, height = 40, label = 'Trend', lineClass = '' } = {}) {
  const points = sparklinePoints(values, { width, height });
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`,
    class: 'mc-spark',
    role: 'img',
    'aria-label': sparkLabel(label, values),
    focusable: 'false',
  });
  if (points.length) {
    svg.append(svgEl('polyline', {
      points: pointsAttr(points),
      class: joinClass('mc-spark-line', lineClass),
      fill: 'none',
    }));
    const last = points[points.length - 1];
    svg.append(svgEl('circle', { cx: last.x, cy: last.y, r: 2.5, class: 'mc-spark-dot' }));
  }
  return svg;
}

// Labelled horizontal bar. The number is shown as text next to the bar, so the bar can be hidden from screen readers.
// showMax: true writes "value of max" instead of the value alone.
export function barRow({ label, value, max, tone, showMax = false } = {}) {
  const v = num(value);
  const m = num(max);
  const share = barShare(value, max);
  let text;
  if (Number.isNaN(v)) text = 'no data';
  else if (showMax && !Number.isNaN(m)) text = `${fmtNum(v)} of ${fmtNum(m)}`;
  else text = fmtNum(v);
  const fill = h('span', { class: joinClass('mc-bar-fill', toneClass(tone)) });
  fill.style.width = `${(share * 100).toFixed(1)}%`;
  return h('div', { class: 'mc-bar-row' },
    h('span', { class: 'mc-bar-label' }, String(label ?? '')),
    h('span', { class: 'mc-bar-track', 'aria-hidden': 'true' }, fill),
    h('span', { class: 'mc-bar-value' }, text));
}

// Ring gauge for a 0..100 percent. Out-of-range values are clamped. NaN shows "no data" and an empty ring.
export function gauge(percent, { label = 'Coverage', tone } = {}) {
  const state = gaugeState(percent);
  const shown = Math.round(state.value);
  const text = state.hasData ? `${shown}%` : 'no data';
  const r = 40;
  const circumference = 2 * Math.PI * r;
  const dash = (state.value / 100) * circumference;
  const svg = svgEl('svg', {
    viewBox: '0 0 100 100',
    class: 'mc-gauge-svg',
    role: 'img',
    'aria-label': `${label}: ${state.hasData ? `${shown} percent` : 'no data'}`,
    focusable: 'false',
  });
  svg.append(svgEl('circle', { cx: 50, cy: 50, r, class: 'mc-gauge-track', fill: 'none' }));
  svg.append(svgEl('circle', {
    cx: 50, cy: 50, r,
    class: joinClass('mc-gauge-arc', toneClass(tone)),
    fill: 'none',
    'stroke-dasharray': `${dash.toFixed(2)} ${circumference.toFixed(2)}`,
    transform: 'rotate(-90 50 50)',
  }));
  return h('span', { class: 'mc-gauge' }, svg, h('span', { class: 'mc-gauge-text' }, text));
}

// Collapsible table. Use it next to a chart so the exact numbers stay available.
// head: [{label, num?, mono?}], rows: arrays of cell values in the same order.
export function tableFallback({ summary = 'Show as table', caption, head, rows, cls = '' }) {
  return h('details', { class: joinClass('mc-table', cls) },
    h('summary', null, summary),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, caption),
        h('thead', null, h('tr', null,
          head.map((col) => h('th', { scope: 'col', class: col.num ? 'num' : null }, col.label)))),
        h('tbody', null, rows.map((row) => h('tr', null,
          row.map((cell, i) => h('td', {
            class: joinClass(head[i] && head[i].num ? 'num' : 'wrap-any', head[i] && head[i].mono ? 'mono' : ''),
          }, cell ?? '—'))))))));
}
