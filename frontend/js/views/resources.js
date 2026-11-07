import { api } from '../api.js';
import { h, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { hasRole } from '../session.js';

// Resource Planner. An illustrative estimate from affected rows and the flood rule pack ratios (SDD 19.x).
// Estimates are SIMULATED_FACT. Viewers can read this page; Analysts run estimates.

const PACK = 'flood';

// Only approved CSV datasets can be used.
export function approvedCsvDatasets(list) {
  return listOf(list).filter((d) => d && d.status === 'APPROVED' && d.kind === 'CSV');
}

// Key names carry the unit (for example drinking_water_litres), so only underscores are replaced.
export function labelFromKey(key) {
  return String(key).replace(/_/g, ' ');
}

// Numbers get locale grouping. Anything else is shown as text, and missing values show a dash.
export function formatValue(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString();
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function assumptionList(assumptions) {
  return Array.isArray(assumptions) ? assumptions.filter((a) => a !== null && a !== undefined).map(String) : [];
}

export async function mount(root, ctx) {
  const { user, signal } = ctx;
  root.append(pageHead('Resource Planner',
    'Illustrative resource estimate from affected rows and the rule pack ratios. Assumptions are shown with the result.'));

  if (!hasRole(user, 'Analyst')) {
    root.append(panel({ title: 'Analyst role needed', style: '--i:1' },
      alertBox('info', 'An Analyst runs resource estimates. You can read this page, but you cannot start an estimate.'),
      h('p', { class: 'muted' }, 'Ask an Analyst to run an estimate for an approved dataset. The result will appear on this page for them.')));
    return;
  }

  const pick = h('select', { id: 'rs-dataset' }, h('option', { value: '' }, 'Loading datasets…'));
  const formErr = h('div', { 'aria-live': 'polite' });
  const runBtn = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Run estimate');
  const resultSlot = h('div', { class: 'stack' });

  const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Run a resource estimate', onsubmit: (e) => {
    e.preventDefault();
    run();
  } },
    h('div', { class: 'field' }, h('label', { for: 'rs-dataset' }, 'Approved CSV dataset'), pick),
    h('div', { class: 'field' }, h('span', { class: 'label' }, 'Rule pack'), h('p', { class: 'mono small' }, PACK)),
    formErr,
    h('div', { class: 'field--wide row' }, runBtn));

  root.append(panel({ title: 'Run an estimate', sub: 'Analyst role. Only approved CSV datasets can be used.', style: '--i:1' }, form), resultSlot);

  async function loadDatasets() {
    try {
      const datasets = approvedCsvDatasets(await api.get('datasets', { signal }));
      if (signal.aborted) return;
      if (!datasets.length) {
        pick.replaceChildren(h('option', { value: '' }, 'No approved CSV datasets yet'));
        resultSlot.replaceChildren(emptyState('No approved datasets', 'Approve a CSV dataset on the Datasets screen first.'));
        return;
      }
      pick.replaceChildren(h('option', { value: '' }, 'Choose a dataset'),
        datasets.map((d) => h('option', { value: d.id }, d.name || d.filename)));
      runBtn.disabled = false;
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
    runBtn.disabled = true;
    resultSlot.replaceChildren(panel({ title: 'Estimate', style: '--i:2' }, spinner('Running the estimate…')));
    try {
      // api.post(path, json, opts): the body is the second argument, and the signal goes in opts.
      const est = await api.post('resources/estimate', { dataset_id: datasetId, pack: PACK }, { signal });
      if (signal.aborted) return;
      resultSlot.replaceChildren(estimatePanel(est || {}));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      resultSlot.replaceChildren(panel({ title: 'Estimate', style: '--i:2' }, errorState(err, run)));
    } finally {
      runBtn.disabled = false;
    }
  }

  await loadDatasets();
}

function estimatePanel(est) {
  const datasetName = (est.dataset && (est.dataset.name || est.dataset.id)) || '—';
  return h('div', { class: 'stack' },
    panel({ title: 'Estimate', sub: `Dataset: ${datasetName} · rule pack ${PACK}`,
      actions: [dataClassBadge('SIMULATED_FACT')], style: '--i:2' },
      alertBox('warn', 'Illustrative estimate, not for operational use.'),
      est.label ? h('p', { class: 'result-label' }, String(est.label)) : null,
      h('h3', { class: 'panel-title' }, 'Estimates'),
      pairTable(est.estimates, 'Estimates', 'Item'),
      h('h3', { class: 'panel-title' }, 'Inputs'),
      pairTable(est.inputs, 'Inputs', 'Input'),
      h('h3', { class: 'panel-title' }, 'Assumptions'),
      assumptionsView(est.assumptions)));
}

// Two-column table for a flat object. Numbers are grouped, and an empty object shows a note.
function pairTable(obj, caption, head) {
  const entries = obj && typeof obj === 'object' ? Object.entries(obj) : [];
  if (!entries.length) return h('p', { class: 'muted' }, 'None reported.');
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, caption),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, head),
        h('th', { scope: 'col', class: 'num' }, 'Value'))),
      h('tbody', null, entries.map(([key, value]) => h('tr', null,
        h('td', { class: 'wrap-any' }, labelFromKey(key)),
        h('td', { class: 'num mono' }, formatValue(value)))))));
}

function assumptionsView(assumptions) {
  const items = assumptionList(assumptions);
  if (!items.length) return h('p', { class: 'muted' }, 'No assumptions were reported.');
  return h('ul', { class: 'assumption-list' }, items.map((text) => h('li', null, text)));
}
