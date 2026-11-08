import { api } from '../api.js';
import { h, short, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { barRow, toneClass } from '../components/mini-charts.js';
import { parseHash } from '../router.js';

// Hazard Intelligence (SDD 19.2). Rule-pack results for approved CSV datasets. The engine output is
// INFERRED_FACT, and the thresholds are illustrative, so the view says so next to every result.
// On open the view runs the newest approved CSV that has the pack's columns. Changing the dataset or the pack re-runs it.

export const PACKS = [
  { id: 'flood', label: 'Flood' },
  { id: 'tsunami', label: 'Tsunami' },
  { id: 'earthquake', label: 'Earthquake' },
  { id: 'wildfire', label: 'Wildfire and smoke' },
];
export const RESULT_ROW_LIMIT = 200;
// Columns each pack needs (backend/app/rules). Matching is case-insensitive, as on the server.
export const REQUIRED_COLUMNS = {
  flood: ['water_depth_cm'],
  tsunami: ['magnitude', 'depth_km'],
  earthquake: ['magnitude'],
  wildfire: ['distance_km'],
};
const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

// Only approved CSV datasets can be analysed.
export function approvedCsvDatasets(list) {
  return listOf(list).filter((d) => d && d.status === 'APPROVED' && d.kind === 'CSV');
}

// Newest first. The sort is stable, so datasets with the same timestamp keep the server's order.
export function newestFirst(list) {
  return [...list].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
}

// Column names of a dataset, lower-cased, from its profile.
export function datasetColumns(dataset) {
  const cols = dataset && dataset.profile && Array.isArray(dataset.profile.columns) ? dataset.profile.columns : [];
  return cols.map((c) => String(c && c.name !== undefined ? c.name : '').trim().toLowerCase());
}

export function requiredColumns(pack) {
  return REQUIRED_COLUMNS[pack] || [];
}

// True when the dataset has every column the pack needs.
export function hasPackColumns(dataset, pack) {
  const have = datasetColumns(dataset);
  return requiredColumns(pack).every((c) => have.includes(c));
}

// The newest approved CSV that has the pack's columns, or null.
export function newestCompatible(list, pack) {
  return newestFirst(list).find((d) => hasPackColumns(d, pack)) || null;
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

// Rows for the severity chips. UNKNOWN always appears, and a missing count shows a dash, not zero.
export function severityRows(countsBySeverity) {
  const counts = countsBySeverity && typeof countsBySeverity === 'object' ? countsBySeverity : {};
  const levels = orderSeverities([...SEVERITY_ORDER, 'UNKNOWN', ...Object.keys(counts)]);
  return levels.map((level) => ({ level, count: counts[level] }));
}

// A candidate value is a list (count is its length) or a number. Anything else gives null.
export function candidateCount(value) {
  if (Array.isArray(value)) return value.length;
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// Affected rows for one district. The flood pack's road-blocked rule is the depth threshold, so it counts the affected rows.
export function affectedRows(entry) {
  if (typeof entry === 'number' && Number.isFinite(entry)) return entry;
  if (!entry || typeof entry !== 'object') return null;
  for (const key of ['affected_rows', 'affected', 'road_blocked_candidates', 'watch_candidates', 'rows']) {
    const value = entry[key];
    if (value !== undefined && value !== null && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
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
  let seq = 0; // Each run gets a number, so a slow older response cannot replace a newer one.

  const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Run a rule pack', onsubmit: (e) => {
    e.preventDefault();
    run();
  } },
    h('div', { class: 'field' }, h('label', { for: 'hz-dataset' }, 'Approved CSV dataset'), pick),
    h('div', { class: 'field' }, h('label', { for: 'hz-pack' }, 'Rule pack'), packSel),
    formErr,
    h('div', { class: 'field--wide row' }, runBtn));

  packSel.addEventListener('change', () => {
    const id = syncSelection(pick.value);
    if (id) run();
    else noCompatible();
  });
  pick.addEventListener('change', () => {
    if (pick.value) run();
  });

  root.append(
    pageHead('Hazard Intelligence',
      'Rule-pack results for approved CSV datasets. Thresholds are illustrative and the results are not for operational use.'),
    panel({ title: 'Run a rule pack', sub: 'Only approved CSV datasets with the pack columns can be analysed. The newest one runs first.', style: '--i:1' }, form),
    resultSlot);

  await loadDatasets();

  // Fills the dataset list for the current pack. Datasets without the pack columns stay visible but disabled.
  function fillDatasetOptions(selectedId) {
    const pack = packSel.value;
    pick.replaceChildren(h('option', { value: '' }, 'Choose a dataset'),
      ...datasets.map((d) => {
        const ok = hasPackColumns(d, pack);
        const name = d.name || d.filename;
        return h('option', { value: d.id, disabled: !ok },
          ok ? name : `${name} (needs ${requiredColumns(pack).join(', ')})`);
      }));
    pick.value = selectedId || '';
  }

  // Keeps the preferred dataset, or the current one, when it has the pack columns. Otherwise it picks the newest compatible one.
  function syncSelection(preferred) {
    const pack = packSel.value;
    const ok = (id) => Boolean(id) && datasets.some((d) => d.id === id && hasPackColumns(d, pack));
    let id = '';
    if (ok(preferred)) id = preferred;
    else if (ok(pick.value)) id = pick.value;
    else {
      const newest = newestCompatible(datasets, pack);
      id = newest ? newest.id : '';
    }
    fillDatasetOptions(id);
    return id;
  }

  function noCompatible() {
    seq += 1;
    const pack = packSel.value;
    const label = packLabel(pack);
    formErr.replaceChildren();
    resultSlot.replaceChildren(emptyState(`No approved dataset has the ${label} columns`,
      `${label} needs: ${requiredColumns(pack).join(', ')}. Upload and approve a CSV with these columns on the Datasets screen.`,
      { icon: 'datasets', actions: [{ label: 'Open Datasets', href: '#/datasets' }] }));
    runBtn.disabled = true;
  }

  async function loadDatasets() {
    try {
      datasets = newestFirst(approvedCsvDatasets(await api.get('datasets', { signal })));
      if (signal.aborted) return;
      if (!datasets.length) {
        pick.replaceChildren(h('option', { value: '' }, 'No approved CSV datasets yet'));
        resultSlot.replaceChildren(emptyState('No approved datasets',
          'Upload a CSV on the Datasets screen and get it approved. Then it can be analysed here.',
          { icon: 'datasets', actions: [{ label: 'Open Datasets', href: '#/datasets' }] }));
        return;
      }
      runBtn.disabled = false;
      const id = syncSelection(initialDataset);
      if (!id) {
        noCompatible();
        return;
      }
      run();
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
    const mine = ++seq;
    runBtn.disabled = true;
    resultSlot.replaceChildren(panel({ title: 'Result', style: '--i:2' }, spinner('Running the rule pack…')));
    try {
      const res = await api.get('hazards', { query: { dataset_id: datasetId, pack }, signal });
      if (signal.aborted || mine !== seq) return;
      resultSlot.replaceChildren(resultPanel(res || {}, pack));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError' || mine !== seq) return;
      resultSlot.replaceChildren(panel({ title: 'Result', style: '--i:2' }, errorState(err, run)));
    } finally {
      if (mine === seq) runBtn.disabled = false;
    }
  }

  function resultPanel(r, pack) {
    const dataset = datasets.find((d) => d.id === pick.value);
    const datasetName = (r.dataset && r.dataset.name) || (dataset && (dataset.name || dataset.filename)) || '—';
    const rows = listOf(r.results);
    return h('div', { class: 'stack analysis' },
      panel({ title: `${packLabel(pack)} result`, sub: `Dataset: ${datasetName}`,
        actions: [dataClassBadge(r.data_class || 'INFERRED_FACT')], style: '--i:2' },
        alertBox('warn', 'Not for operational use. Thresholds are illustrative and not validated.'),
        h('dl', { class: 'kv-list' },
          kv('Rule pack', packLine(r.rule_pack)),
          kv('Pack SHA-256', hashSpan(r.rule_pack && r.rule_pack.sha256)),
          kv('Threshold status', (r.thresholds && r.thresholds.status) || '—'),
          kv('Rows evaluated', fmtCount(r.rows_evaluated)),
          kv('Unknown depth rows', fmtCount(r.rows_unknown_depth))),
        h('h3', { class: 'panel-title' }, 'Rows by severity'),
        severityChips(r.counts_by_severity),
        h('p', { class: 'hint' }, 'UNKNOWN means the rule could not classify the row. It is not zero.')),
      candidateTiles(r),
      r.per_district && typeof r.per_district === 'object'
        ? panel({ title: 'Per district', sub: 'Bar: affected rows, scaled to the largest district.', style: '--i:3' },
          districtBars(r.per_district))
        : null,
      h('details', { class: 'analysis-details' },
        h('summary', null, `Full result list (${resultsSub(rows)})`),
        resultsTable(rows),
        candidateLists(r)));
  }
}

function packLabel(pack) {
  return (PACKS.find((p) => p.id === pack) || {}).label || pack;
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

function fmtCount(value) {
  const n = Number(value);
  return value === null || value === undefined || value === '' || !Number.isFinite(n) ? '—' : n.toLocaleString();
}

// One chip per severity. The chip classes come from command.css. UNKNOWN has no tone, so it gets a muted chip.
function severityChips(counts) {
  return h('ul', { class: 'analysis-chips' }, severityRows(counts).map(({ level, count }) => h('li', null,
    h('span', { class: ['sev-chip', toneClass(level) || 'analysis-chip-unknown'].join(' ') }, level),
    h('strong', { class: 'mono analysis-count' }, fmtCount(count)))));
}

// Road blocked and watch candidate counts. A pack that does not report one shows a dash and a note.
function candidateTiles(r) {
  const tiles = [
    { label: 'Road blocked candidates', value: r.road_blocked_candidates },
    { label: 'Watch candidates', value: r.watch_candidates },
  ];
  return h('div', { class: 'analysis-tiles' }, tiles.map(({ label, value }) => {
    const count = candidateCount(value);
    return h('div', { class: 'analysis-tile' },
      h('span', { class: 'analysis-tile-label' }, label),
      h('strong', { class: 'analysis-tile-value mono' }, count === null ? '—' : count.toLocaleString()),
      h('span', { class: 'hint' }, value === undefined ? 'Not reported by this pack' : 'Rows flagged by the rule pack'));
  }));
}

// Affected rows per district, drawn with barRow. The label is for screen readers only (see analysis.css).
function districtBars(perDistrict) {
  const entries = Object.entries(perDistrict);
  if (!entries.length) return emptyState('No districts', 'The rule pack produced no district counts.');
  const values = entries.map(([, v]) => affectedRows(v));
  const max = Math.max(0, ...values.map((v) => (v === null ? 0 : v)));
  const field = (entry, key) => (entry && typeof entry === 'object' ? fmtCount(entry[key]) : '—');
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('caption', { class: 'sr-only' }, 'Affected rows per district'),
    h('thead', null, h('tr', null,
      h('th', { scope: 'col' }, 'District'),
      h('th', { scope: 'col' }, 'Affected rows'),
      h('th', { scope: 'col', class: 'num' }, 'Rows'),
      h('th', { scope: 'col', class: 'num' }, 'Road blocked'),
      h('th', { scope: 'col', class: 'num' }, 'Unknown depth'))),
    h('tbody', null, entries.map(([district, entry], i) => h('tr', null,
      h('td', { class: 'wrap-any' }, district),
      h('td', { class: 'analysis-bar-cell' }, barRow({ label: `${district}: affected rows`, value: values[i], max, showMax: true })),
      h('td', { class: 'num mono' }, field(entry, 'rows')),
      h('td', { class: 'num mono' }, field(entry, 'road_blocked_candidates')),
      h('td', { class: 'num mono' }, field(entry, 'unknown_depth_rows')))))));
}

function resultsSub(results) {
  const total = listOf(results).length;
  if (total > RESULT_ROW_LIMIT) return `first ${RESULT_ROW_LIMIT} of ${total} rows`;
  return `${total} row(s)`;
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

// Candidate lists (only when a pack sends rows, not counts) appear inside the details element.
function candidateLists(r) {
  const keys = ['road_blocked_candidates', 'watch_candidates'].filter((key) => Array.isArray(r[key]));
  return keys.map((key) => h('div', null,
    h('h3', { class: 'panel-title' }, key === 'watch_candidates' ? 'Watch candidates' : 'Road blocked candidates'),
    genericTable(r[key], key)));
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
