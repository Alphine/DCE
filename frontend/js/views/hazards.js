import { api } from '../api.js';
import { h, short, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { parseHash } from '../router.js';

// Hazard Intelligence (SDD 19.2). Rule-pack results for approved CSV datasets. The engine output is
// INFERRED_FACT, and the thresholds are illustrative, so the view says so next to every result.

export const PACKS = [
  { id: 'flood', label: 'Flood' },
  { id: 'tsunami', label: 'Tsunami' },
  { id: 'earthquake', label: 'Earthquake' },
  { id: 'wildfire', label: 'Wildfire and smoke' },
];
export const RESULT_ROW_LIMIT = 200;
const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const CANDIDATE_TITLES = { watch_candidates: 'Watch candidates', road_blocked_candidates: 'Road blocked candidates' };

// Only approved CSV datasets can be analysed.
export function approvedCsvDatasets(list) {
  return listOf(list).filter((d) => d && d.status === 'APPROVED' && d.kind === 'CSV');
}

// Short, readable text for any server value. Never returns HTML.
export function cellText(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) {
    const parts = value.filter((v) => v !== null && typeof v !== 'object').map(String);
    return parts.length ? parts.join(', ') : '—';
  }
  if (typeof value === 'object') return short(JSON.stringify(value), 120);
  return String(value);
}

// Severity keys in a fixed order: known levels first, then any others, then UNKNOWN last.
export function orderSeverities(keys) {
  const unique = [...new Set(keys)];
  const known = SEVERITY_ORDER.filter((k) => unique.includes(k));
  const other = unique.filter((k) => !SEVERITY_ORDER.includes(k) && k !== 'UNKNOWN').sort();
  return [...known, ...other, ...(unique.includes('UNKNOWN') ? ['UNKNOWN'] : [])];
}

// Rows for the severity table. UNKNOWN always appears, and a missing count shows a dash, not zero.
export function severityRows(countsBySeverity) {
  const counts = countsBySeverity && typeof countsBySeverity === 'object' ? countsBySeverity : {};
  const levels = orderSeverities([...SEVERITY_ORDER, 'UNKNOWN', ...Object.keys(counts)]);
  return levels.map((level) => ({ level, count: counts[level] }));
}

// The results table shows the first RESULT_ROW_LIMIT rows. District and area columns appear only when used.
export function resultColumns(results) {
  const sample = results.slice(0, RESULT_ROW_LIMIT);
  const has = (key) => sample.some((r) => r && r[key] !== undefined && r[key] !== null);
  const cols = [
    { key: 'row', label: 'Row' },
    { key: 'severity', label: 'Severity' },
    { key: 'flags', label: 'Flags' },
  ];
  if (has('district')) cols.push({ key: 'district', label: 'District' });
  if (has('area')) cols.push({ key: 'area', label: 'Area' });
  return cols;
}

export async function mount(root, ctx) {
  const { signal } = ctx;
  const initialDataset = parseHash().query.get('dataset') || '';
  const pick = h('select', { id: 'hz-dataset', required: true }, h('option', { value: '' }, 'Loading datasets…'));
  const packSel = h('select', { id: 'hz-pack' }, PACKS.map((p) => h('option', { value: p.id }, p.label)));
  const formErr = h('div', { 'aria-live': 'polite' });
  const runBtn = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Run analysis');
  const resultSlot = h('div', { class: 'stack' });
  let datasets = [];

  const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Run a rule pack', onsubmit: (e) => {
    e.preventDefault();
    run();
  } },
    h('div', { class: 'field' }, h('label', { for: 'hz-dataset' }, 'Approved CSV dataset'), pick),
    h('div', { class: 'field' }, h('label', { for: 'hz-pack' }, 'Rule pack'), packSel),
    formErr,
    h('div', { class: 'field--wide row' }, runBtn));

  root.append(
    pageHead('Hazard Intelligence',
      'Rule-pack results for approved CSV datasets. Thresholds are illustrative and the results are not for operational use.'),
    panel({ title: 'Run a rule pack', sub: 'Only approved CSV datasets can be analysed.', style: '--i:1' }, form),
    resultSlot);

  async function loadDatasets() {
    try {
      datasets = approvedCsvDatasets(await api.get('datasets', { signal }));
      if (signal.aborted) return;
      if (!datasets.length) {
        pick.replaceChildren(h('option', { value: '' }, 'No approved CSV datasets yet'));
        resultSlot.replaceChildren(emptyState('No approved datasets',
          'Upload a CSV on the Datasets screen and get it approved. Then it can be analysed here.',
          { icon: 'datasets', actions: [{ label: 'Open Datasets', href: '#/datasets' }] }));
        return;
      }
      pick.replaceChildren(h('option', { value: '' }, 'Choose a dataset'),
        datasets.map((d) => h('option', { value: d.id }, d.name || d.filename)));
      if (initialDataset && datasets.some((d) => d.id === initialDataset)) pick.value = initialDataset;
      runBtn.disabled = false;
      if (pick.value) run();
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      pick.replaceChildren(h('option', { value: '' }, 'Could not load datasets'));
      formErr.replaceChildren(alertBox('error', err.message));
    }
  }

  async function run() {
    formErr.replaceChildren();
    const datasetId = pick.value;
    if (!datasetId) {
      formErr.replaceChildren(alertBox('error', 'Choose an approved dataset first.'));
      return;
    }
    const pack = packSel.value;
    runBtn.disabled = true;
    resultSlot.replaceChildren(panel({ title: 'Result', style: '--i:2' }, spinner('Running the rule pack…')));
    try {
      const res = await api.get('hazards', { query: { dataset_id: datasetId, pack }, signal });
      if (signal.aborted) return;
      resultSlot.replaceChildren(resultPanel(res || {}, pack));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      resultSlot.replaceChildren(panel({ title: 'Result', style: '--i:2' }, errorState(err, run)));
    } finally {
      runBtn.disabled = false;
    }
  }

  function resultPanel(r, pack) {
    const dataset = datasets.find((d) => d.id === pick.value);
    const datasetName = (r.dataset && r.dataset.name) || (dataset && (dataset.name || dataset.filename)) || '—';
    const packLabel = (PACKS.find((p) => p.id === pack) || {}).label || pack;
    return h('div', { class: 'stack' },
      panel({ title: `${packLabel} result`, sub: `Dataset: ${datasetName}`, actions: [dataClassBadge(r.data_class || 'INFERRED_FACT')], style: '--i:2' },
        alertBox('warn', `Illustrative thresholds. These results are not for operational use.${r.label || (r.thresholds && r.thresholds.status) ? ` ${r.label || r.thresholds.status}` : ''}`),
        h('dl', { class: 'kv-list' },
          kv('Rule pack', packLine(r.rule_pack)),
          kv('Pack SHA-256', hashSpan(r.rule_pack && r.rule_pack.sha256)),
          kv('Dataset', datasetName),
          kv('Result rows', r.results ? String(listOf(r.results).length) : '—')),
        h('h3', { class: 'panel-title' }, 'Rows by severity'),
        severityTable(r.counts_by_severity),
        h('p', { class: 'hint' }, 'UNKNOWN means the rule could not classify the row. It is not zero.')),
      ...candidatePanels(r),
      r.per_district && typeof r.per_district === 'object'
        ? panel({ title: 'Per district', style: '--i:3' }, districtTable(r.per_district)) : null,
      panel({ title: 'Rows', sub: resultsSub(r.results), style: '--i:3' }, resultsTable(listOf(r.results))));
  }

  function candidatePanels(r) {
    return Object.keys(CANDIDATE_TITLES)
      .filter((key) => Array.isArray(r[key]))
      .map((key, i) => panel({ title: CANDIDATE_TITLES[key], sub: `${r[key].length} listed`, style: `--i:${3 + i}` },
        genericTable(r[key], 'Candidates')));
  }

  await loadDatasets();
}

function packLine(pack) {
  if (!pack) return '—';
  const version = pack.version ? ` v${pack.version}` : '';
  return `${pack.pack_id || '—'}${version}`;
}

function hashSpan(sha) {
  if (!sha) return '—';
  return h('span', { class: 'hash', title: String(sha) }, short(sha, 16));
}

function severityTable(counts) {
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, 'Rows by severity'),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, 'Severity'),
        h('th', { scope: 'col', class: 'num' }, 'Rows'))),
      h('tbody', null, severityRows(counts).map((row) => h('tr', null,
        h('td', null, row.level),
        h('td', { class: 'num mono' }, row.count === undefined || row.count === null ? '—' : Number(row.count).toLocaleString()))))));
}

function districtTable(perDistrict) {
  const entries = Object.entries(perDistrict);
  const levels = orderSeverities(entries.flatMap(([, v]) => (v && typeof v === 'object' ? Object.keys(v) : [])));
  const numeric = levels.length > 0;
  const columns = numeric ? levels : ['Rows'];
  if (!entries.length) return emptyState('No districts', 'The rule pack produced no district counts.');
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, 'Counts per district'),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, 'District'),
        columns.map((c) => h('th', { scope: 'col', class: 'num' }, c)))),
      h('tbody', null, entries.map(([district, value]) => h('tr', null,
        h('td', { class: 'wrap-any' }, district),
        (numeric ? columns : ['Rows']).map((c) => h('td', { class: 'num mono' },
          cellText(numeric ? (value && typeof value === 'object' ? value[c] : undefined) : value))))))));
}

function resultsSub(results) {
  const total = listOf(results).length;
  if (total > RESULT_ROW_LIMIT) return `Showing the first ${RESULT_ROW_LIMIT} of ${total} rows.`;
  return `${total} row(s).`;
}

function resultsTable(results) {
  if (!results.length) return emptyState('No rows', 'The rule pack returned no row results.');
  const cols = resultColumns(results);
  const rows = results.slice(0, RESULT_ROW_LIMIT);
  const head = h('thead', null, h('tr', null, cols.map((c) => h('th', { scope: 'col' }, c.label))));
  const body = h('tbody', null, rows.map((r) => resultRow(r, cols)));
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('caption', { class: 'sr-only' }, 'Row results'), head, body));
}

function resultRow(r, cols) {
  return h('tr', null, cols.map((c) => h('td', { class: c.key === 'flags' ? 'wrap-any' : null }, cellText(r && r[c.key]))));
}

// Generic table for candidate lists. Each item may be an object (columns from its scalar keys) or a plain value.
function genericTable(items, caption) {
  if (!items.length) return emptyState('None', 'Nothing matched this rule.');
  const objects = items.filter((it) => it && typeof it === 'object' && !Array.isArray(it));
  const keys = [];
  for (const it of objects.slice(0, 50)) {
    for (const k of Object.keys(it)) if (!keys.includes(k)) keys.push(k);
  }
  const cols = objects.length ? keys : ['value'];
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, caption),
      h('thead', null, h('tr', null, cols.map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', null, items.map((it) => h('tr', null, cols.map((c) => h('td', { class: 'wrap-any' },
        cellText(objects.length ? (it && typeof it === 'object' ? it[c] : undefined) : it))))))));
}
