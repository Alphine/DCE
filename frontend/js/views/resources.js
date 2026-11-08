import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { barRow, coveragePercent, gauge, tableFallback } from '../components/mini-charts.js';
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

  // The estimate sits in its own slot so the coverage section (read by every role) can follow it.
  const estimateSlot = h('div', { class: 'stack' });
  root.append(estimateSlot);
  coverageSection(root, ctx);

  if (!hasRole(user, 'Analyst')) {
    estimateSlot.append(panel({ title: 'Analyst role needed', style: '--i:1' },
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

  estimateSlot.append(panel({ title: 'Run an estimate', sub: 'Analyst role. Only approved CSV datasets can be used.', style: '--i:1' }, form), resultSlot);

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

// Every role can read coverage. It needs a stored simulation run, and it uses the same planning endpoint as Planning.
function coverageSection(root, { signal }) {
  const runSelect = h('select', { id: 'rs-run' }, h('option', { value: '' }, 'Loading runs…'));
  const err = h('div', { 'aria-live': 'polite' });
  const showBtn = h('button', { class: 'btn', type: 'submit', disabled: true }, 'Show coverage');
  const slot = h('div', { class: 'stack' });

  const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Show coverage for a simulation run',
    onsubmit: (e) => {
      e.preventDefault();
      show();
    } },
  h('div', { class: 'field' }, h('label', { for: 'rs-run' }, 'Simulation run'), runSelect),
  err,
  h('div', { class: 'field--wide row' }, showBtn));
  root.append(panel({ title: 'Coverage', sub: 'Need from a simulation run, compared with logistics stock and capacity.',
    style: '--i:3' }, form), slot);

  loadRuns();

  async function loadRuns() {
    try {
      const runs = listOf(await api.get('simulations', { signal }));
      if (signal.aborted) return;
      if (!runs.length) {
        runSelect.replaceChildren(h('option', { value: '' }, 'No simulation runs yet'));
        slot.replaceChildren(emptyState('No simulation runs yet', 'Create a run on the Simulation screen first.'));
        return;
      }
      runSelect.replaceChildren(h('option', { value: '' }, 'Choose a run'),
        runs.map((r) => h('option', { value: r.id }, `${r.name} · ${fmtDate(r.created_at)}`)));
      showBtn.disabled = false;
    } catch (loadErr) {
      if (signal.aborted || loadErr.name === 'AbortError') return;
      runSelect.replaceChildren(h('option', { value: '' }, 'Could not load runs'));
      err.replaceChildren(alertBox('error', loadErr.message));
    }
  }

  async function show() {
    err.replaceChildren();
    const id = runSelect.value;
    if (!id) {
      err.replaceChildren(alertBox('error', 'Choose a simulation run first.'));
      return;
    }
    showBtn.disabled = true;
    slot.replaceChildren(panel({ title: 'Coverage', style: '--i:4' }, spinner('Comparing need with logistics…')));
    try {
      const plan = await api.get(`planning/allocation?simulation_id=${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      slot.replaceChildren(coverageView(plan));
    } catch (showErr) {
      if (signal.aborted || showErr.name === 'AbortError') return;
      slot.replaceChildren(panel({ title: 'Coverage', style: '--i:4' }, errorState(showErr, show)));
    } finally {
      showBtn.disabled = false;
    }
  }
}

// Flat list of every gap, with its district, in the order the planner ranked the districts.
export function coverageGaps(coverage) {
  return (Array.isArray(coverage) ? coverage : [])
    .flatMap((row) => (Array.isArray(row.gaps) ? row.gaps.map((gap) => ({ district: row.district, ...gap })) : []));
}

// "need / stock" for one item, with dashes for missing numbers.
function needOverStock(need, stock) {
  return `${formatValue(need)} / ${formatValue(stock)}`;
}

export function coverageView(plan) {
  const rows = Array.isArray(plan && plan.coverage) ? plan.coverage : [];
  if (!rows.length) {
    return panel({ title: 'Coverage', style: '--i:4' },
      emptyState('No logistics coverage to show',
        'Add shelters, supplies, vehicles or teams on the Logistics screen. Coverage stays empty until some are recorded.'));
  }
  const gaps = coverageGaps(rows);
  return h('div', { class: 'stack' },
    panel({ title: 'Coverage', sub: 'Need against stock on hand and matching capacity, by district.',
      actions: [dataClassBadge('SIMULATED_FACT')], style: '--i:4' },
    alertBox('warn', 'Need is simulated and illustrative. Stock and capacity are as recorded in the logistics registry.'),
    h('div', { class: 'mc-cov-grid' }, rows.map(districtCard)),
    tableFallback({
      summary: 'Show coverage as table',
      caption: 'Coverage by district. Each item shows need / stock.',
      head: [
        { label: 'District' },
        { label: 'People needed', num: true },
        { label: 'Capacity (people)', num: true },
        { label: 'People short', num: true },
        { label: 'Water packs', num: true },
        { label: 'Food packs', num: true },
        { label: 'Shelter kits', num: true },
        { label: 'Teams (rescue / medical / transport)' },
      ],
      rows: rows.map((row) => {
        const need = row.need || {};
        const stock = row.stock || {};
        const capacity = row.capacity || {};
        const teams = row.teams_available || {};
        return [
          row.district,
          formatValue(need.people_estimated),
          formatValue(capacity.total_people),
          formatValue(row.people_gap),
          needOverStock(need.water_packs, stock.water_packs),
          needOverStock(need.food_packs, stock.food_packs),
          needOverStock(need.shelter_kits, stock.shelter_kits),
          `${formatValue(teams.RESCUE)} / ${formatValue(teams.MEDICAL)} / ${formatValue(teams.TRANSPORT)}`,
        ];
      }),
    })),
    panel({ title: 'Gaps', sub: gaps.length ? `${gaps.length} item(s) below need` : 'No gaps', style: '--i:5' },
      gaps.length
        ? h('ul', { class: 'assumption-list' }, gaps.map((gap) => h('li', null,
          `${gap.district}: ${labelFromKey(gap.item)} short by ${formatValue(gap.shortfall)} (need ${formatValue(gap.need)}, stock ${formatValue(gap.stock)})`)))
        : h('p', { class: 'muted' }, 'Stock meets the need in every allocated district.')));
}

// Tone for a coverage percent: under 100 is a gap (HIGH), 100 or more is covered (LOW), and no data has no tone.
function coverageTone(pct) {
  if (Number.isNaN(pct)) return undefined;
  return pct < 100 ? 'HIGH' : 'LOW';
}

// One district: a gauge for people capacity against need, then stock against need for each supply item.
function districtCard(row) {
  const need = row.need || {};
  const stock = row.stock || {};
  const capacity = row.capacity || {};
  const teams = row.teams_available || {};
  const peoplePct = coveragePercent(capacity.total_people, need.people_estimated);
  const items = [
    ['Water packs', stock.water_packs, need.water_packs],
    ['Food packs', stock.food_packs, need.food_packs],
    ['Shelter kits', stock.shelter_kits, need.shelter_kits],
  ];
  return h('article', { class: 'mc-district' },
    h('h3', { class: 'mc-district-name' }, row.district || '(no district)'),
    h('div', { class: 'mc-district-head' },
      gauge(peoplePct, { label: `${row.district || 'District'}: capacity against people needed`, tone: coverageTone(peoplePct) }),
      h('p', { class: 'small' },
        `${formatValue(capacity.total_people)} capacity for ${formatValue(need.people_estimated)} people needed. ${formatValue(row.people_gap)} short.`)),
    h('div', { class: 'mc-district-bars' },
      items.map(([label, have, want]) => barRow({
        label: `${label} (stock / need)`,
        value: have,
        max: want,
        showMax: true,
        tone: coverageTone(coveragePercent(have, want)),
      }))),
    h('p', { class: 'small muted' },
      `Teams available: rescue ${formatValue(teams.RESCUE)}, medical ${formatValue(teams.MEDICAL)}, transport ${formatValue(teams.TRANSPORT)}.`));
}

function assumptionsView(assumptions) {
  const items = assumptionList(assumptions);
  if (!items.length) return h('p', { class: 'muted' }, 'No assumptions were reported.');
  return h('ul', { class: 'assumption-list' }, items.map((text) => h('li', null, text)));
}
