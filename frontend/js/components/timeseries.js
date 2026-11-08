// Hourly report intake as two sparklines (all reports, verified), with the exact numbers in a <details> table.
// Built with h() and createElementNS through mini-charts.js. Server data is only ever set as text.
import { h } from '../dom.js';
import { sparkline, tableFallback, fmtNum } from './mini-charts.js';

const SERIES = [
  { key: 'reports', label: 'All reports per hour', lineClass: 'mc-spark-line--reports' },
  { key: 'verified', label: 'Verified per hour', lineClass: 'mc-spark-line--verified' },
];

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

  const n = buckets.length;
  const range = `${shortHour(buckets[0].hour)} to ${shortHour(buckets[n - 1].hour)} UTC`;

  const stacks = SERIES.map((series) => {
    const values = buckets.map((b) => b[series.key]);
    return h('div', { class: 'mc-series' },
      h('div', { class: 'mc-series-head' },
        h('span', null, series.label),
        h('strong', { class: 'num' }, `latest hour ${fmtNum(values[n - 1])}`)),
      sparkline(values, {
        width: 720,
        height: 56,
        label: `${series.label}, ${n} hours (UTC)`,
        lineClass: series.lineClass,
      }));
  });

  return h('figure', { class: 'ts mc-ts' },
    h('div', { class: 'mc-ts-stack' }, stacks),
    h('p', { class: 'mc-series-range small muted' }, range),
    tableFallback({
      summary: 'Show as table',
      caption: `${title}, one row per hour`,
      cls: 'ts-table',
      head: [
        { label: 'Hour (UTC)', mono: true },
        { label: 'All reports', num: true },
        { label: 'Verified', num: true },
      ],
      rows: buckets.map((b) => [shortHour(b.hour), fmtNum(b.reports ?? 0), fmtNum(b.verified ?? 0)]),
    }));
}
