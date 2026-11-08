import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv, short } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { copyButton } from '../components/copy.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { hasRole } from '../session.js';
import { approvedCsvDatasets } from './resources.js';

// What-if simulation (SDD 14). Every run is SIMULATED_FACT with illustrative parameters (SDD 14.5).
// Analysts create runs. Everyone can read them. Limits here mirror the server, which checks again.

export const SIM_LABEL = 'Simulation — illustrative parameters';
export const LIMITS = Object.freeze({
  depthMin: 0.1, depthMax: 3, riseMax: 100, hoursMin: 1, hoursMax: 72, nameMax: 120,
});

// Returns a client-side message, or null when the run can be sent.
export function validateRun(f) {
  if (!f.dataset_id) return 'Choose an approved dataset.';
  if (!f.name || !f.name.trim()) return 'Give the scenario a name.';
  if (f.name.trim().length > LIMITS.nameMax) return `Keep the name under ${LIMITS.nameMax} characters.`;
  const depth = Number(f.depth_multiplier);
  if (!Number.isFinite(depth) || depth < LIMITS.depthMin || depth > LIMITS.depthMax) {
    return `Depth multiplier must be between ${LIMITS.depthMin} and ${LIMITS.depthMax}.`;
  }
  const rise = Number(f.rise_cm_per_hour);
  if (!Number.isFinite(rise) || rise < 0 || rise > LIMITS.riseMax) {
    return `Rise per hour must be between 0 and ${LIMITS.riseMax} cm.`;
  }
  const hours = Number(f.hours);
  if (!Number.isInteger(hours) || hours < LIMITS.hoursMin || hours > LIMITS.hoursMax) {
    return `Horizon must be a whole number of hours from ${LIMITS.hoursMin} to ${LIMITS.hoursMax}.`;
  }
  return null;
}

// JSON body for POST /api/simulations. Numbers are sent as numbers, never as text.
export function runBody(f) {
  return {
    dataset_id: f.dataset_id,
    name: f.name.trim(),
    pack: 'flood',
    depth_multiplier: Number(f.depth_multiplier),
    rise_cm_per_hour: Number(f.rise_cm_per_hour),
    hours: Number(f.hours),
  };
}

// Bar heights as a share of the largest value, so an all-zero timeline draws flat bars, not NaN.
export function barShares(values) {
  const nums = values.map((v) => (Number.isFinite(v) && v > 0 ? v : 0));
  const max = Math.max(0, ...nums);
  return nums.map((v) => (max === 0 ? 0 : v / max));
}

export function sampleTimeline(timeline, maxBars = 72) {
  if (timeline.length <= maxBars) return timeline;
  const step = Math.ceil(timeline.length / maxBars);
  return timeline.filter((_, i) => i % step === 0 || i === timeline.length - 1);
}

export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;

  root.append(pageHead('Simulation',
    'Explore how flooding could develop under stated assumptions. Results are illustrative and never observations.'));

  if (hasRole(user, 'Analyst')) root.append(newRunPanel());

  const listSlot = h('div', null, spinner('Loading runs…'));
  root.append(panel({ title: 'Scenario runs',
    sub: 'Newest first. Each run keeps its inputs and the hash of its output.', style: '--i:2' }, listSlot));
  const detailSlot = h('div', { class: 'stack' });
  root.append(detailSlot);

  async function refreshList() {
    try {
      const runs = listOf(await api.get('simulations', { signal }));
      if (signal.aborted) return;
      renderList(runs);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, refreshList));
    }
  }

  function renderList(runs) {
    if (!runs.length) {
      listSlot.replaceChildren(emptyState('No runs yet',
        hasRole(user, 'Analyst')
          ? 'Start a scenario above. It will appear here with its inputs and output hash.'
          : 'Scenario runs created by an Analyst will appear here.'));
      return;
    }
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Scenario runs'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Scenario'),
          h('th', { scope: 'col' }, 'Dataset'),
          h('th', { scope: 'col', class: 'num' }, 'Peak hour'),
          h('th', { scope: 'col', class: 'num' }, 'Peak affected'),
          h('th', { scope: 'col' }, 'Created'))),
        h('tbody', null, runs.map((r) => h('tr', { class: r.id === selectedId ? 'row-link is-selected' : 'row-link' },
          h('td', { class: 'wrap-any' }, h('a', { href: `#/simulation/${encodeURIComponent(r.id)}` }, r.name)),
          h('td', { class: 'wrap-any' }, (r.dataset && r.dataset.name) || '—'),
          h('td', { class: 'num' }, String(r.peak.hour)),
          h('td', { class: 'num' }, String(r.peak.affected_rows)),
          h('td', null, fmtDate(r.created_at))))))));
  }

  function newRunPanel() {
    const err = h('div', { 'aria-live': 'polite' });
    const pick = h('select', { id: 'sm-dataset', required: true }, h('option', { value: '' }, 'Loading datasets…'));
    const name = h('input', { id: 'sm-name', type: 'text', maxlength: String(LIMITS.nameMax), required: true,
      placeholder: 'For example: Heavy rain, next 24 hours' });
    const depth = h('input', { id: 'sm-depth', type: 'number', step: '0.1', min: String(LIMITS.depthMin),
      max: String(LIMITS.depthMax), value: '1' });
    const rise = h('input', { id: 'sm-rise', type: 'number', step: '1', min: '0', max: String(LIMITS.riseMax), value: '0' });
    const hours = h('input', { id: 'sm-hours', type: 'number', step: '1', min: String(LIMITS.hoursMin),
      max: String(LIMITS.hoursMax), value: '24' });
    const submit = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Run scenario');
    const preview = h('p', { class: 'small muted field--wide', 'aria-live': 'polite' });

    const updatePreview = () => {
      const d = Number(depth.value);
      const r = Number(rise.value);
      const hr = Number(hours.value);
      if (Number.isFinite(d) && Number.isFinite(r) && Number.isInteger(hr)) {
        preview.textContent = `At hour ${hr}, depth = base depth × ${d} + ${r} cm × ${hr}. Hour 0 uses base depth × ${d}.`;
      } else {
        preview.textContent = '';
      }
    };
    [depth, rise, hours].forEach((el) => el.addEventListener('input', updatePreview));
    updatePreview();

    api.get('datasets', { signal }).then((list) => {
      if (signal.aborted) return;
      const sets = approvedCsvDatasets(list);
      if (!sets.length) {
        pick.replaceChildren(h('option', { value: '' }, 'No approved CSV datasets'));
        return;
      }
      pick.replaceChildren(h('option', { value: '' }, 'Choose a dataset'),
        sets.map((d) => h('option', { value: d.id }, d.name || d.filename)));
      submit.disabled = false;
    }).catch((error) => {
      if (signal.aborted || error.name === 'AbortError') return;
      pick.replaceChildren(h('option', { value: '' }, 'Could not load datasets'));
      err.replaceChildren(alertBox('error', error.message));
    });

    const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Run a scenario', onsubmit: async (e) => {
      e.preventDefault();
      err.replaceChildren();
      const values = {
        dataset_id: pick.value, name: name.value, depth_multiplier: depth.value,
        rise_cm_per_hour: rise.value, hours: hours.value,
      };
      const problem = validateRun(values);
      if (problem) { err.replaceChildren(alertBox('error', problem)); return; }
      submit.disabled = true;
      submit.textContent = 'Running…';
      try {
        const run = await api.post('simulations', runBody(values), { signal });
        toast('Scenario run saved.');
        await refreshList();
        go(`#/simulation/${encodeURIComponent(run.id)}`);
      } catch (error) {
        if (error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      } finally {
        submit.disabled = false;
        submit.textContent = 'Run scenario';
      }
    } },
      h('div', { class: 'field' }, h('label', { for: 'sm-dataset' }, 'Approved CSV dataset'), pick),
      h('div', { class: 'field' }, h('label', { for: 'sm-name' }, 'Scenario name'), name),
      h('div', { class: 'field' }, h('label', { for: 'sm-depth' }, 'Depth multiplier'), depth,
        h('span', { class: 'hint' }, `From ${LIMITS.depthMin} to ${LIMITS.depthMax}. 1 keeps observed depths.`)),
      h('div', { class: 'field' }, h('label', { for: 'sm-rise' }, 'Rise per hour (cm)'), rise,
        h('span', { class: 'hint' }, 'Added to every known depth for each hour.')),
      h('div', { class: 'field' }, h('label', { for: 'sm-hours' }, 'Horizon (hours)'), hours,
        h('span', { class: 'hint' }, `From ${LIMITS.hoursMin} to ${LIMITS.hoursMax}.`)),
      preview,
      err,
      h('div', { class: 'field--wide row' }, submit));

    return panel({ title: 'New scenario', sub: 'Analyst role. Only approved CSV datasets with water depths can be used.',
      style: '--i:1' }, form);
  }

  async function renderDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Run', style: '--i:3' }, spinner('Loading run…')));
    try {
      const run = await api.get(`simulations/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      detailSlot.replaceChildren(runDetail(run, user));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Run', style: '--i:3' }, errorState(err, () => renderDetail(id))));
    }
  }

  await refreshList();
  if (selectedId) await renderDetail(selectedId);
}

export function runDetail(run) {
  const out = run.output || {};
  const last = out.timeline && out.timeline.length ? out.timeline[out.timeline.length - 1] : null;
  const peakPoint = out.timeline ? out.timeline[run.peak.hour] : null;
  const unknown = out.rows_unknown_base_depth || 0;
  const total = out.rows_total || 0;
  const roadBlocked = peakPoint ? peakPoint.road_blocked_candidates : 0;

  const tiles = h('div', { class: 'tiles' },
    tile('Peak hour', `${run.peak.hour} h`, 'First hour with the most affected rows'),
    tile('Affected at peak', String(run.peak.affected_rows), `of ${total.toLocaleString()} rows`),
    tile('Road blocked candidates', String(roadBlocked), 'At the peak hour, from the flood pack'),
    tile('Unknown base depth', String(unknown), last ? 'Not counted as affected' : ''));

  return h('div', { class: 'stack' },
    panel({ title: run.name, sub: `${run.dataset.name || 'Dataset'} · created ${fmtDate(run.created_at)}`,
      actions: [dataClassBadge('SIMULATED_FACT')], style: '--i:3' },
      alertBox('warn', SIM_LABEL + '. Not for operational use.'),
      tiles,
      h('h3', { class: 'panel-title' }, 'Hour by hour'),
      timelineChart(out.timeline || [], run.peak.hour),
      h('p', { class: 'small muted' }, 'The amber bar marks the peak hour: the first hour with the most affected rows.'),
      timelineTable(out.timeline || [])),
    panel({ title: 'Peak by district', sub: `Snapshot at hour ${run.peak.hour}`, style: '--i:4' },
      perDistrictTable(out.peak ? out.peak.per_district : {})),
    panel({ title: 'Inputs and reproducibility', sub: 'Everything needed to rerun this scenario and check its output.', style: '--i:5' },
      h('dl', { class: 'kv-list' },
        kv('Depth multiplier', String(run.parameters.depth_multiplier)),
        kv('Rise per hour', `${run.parameters.rise_cm_per_hour} cm`),
        kv('Horizon', `${run.parameters.hours} hours`),
        kv('Dataset', run.dataset.name || '—'),
        kv('Dataset hash', hashCell(run.dataset_sha256)),
        kv('Rule pack', `${run.pack.id} · ${hashShort(run.pack.sha256)}`),
        kv('Simulator', run.simulator_version),
        kv('Output hash', hashCell(run.output_sha256))),
      h('h3', { class: 'panel-title' }, 'Model'),
      h('p', { class: 'mono small' }, out.model || '—'),
      h('h3', { class: 'panel-title' }, 'Assumptions'),
      assumptionsView(out.assumptions),
      h('div', { class: 'row' },
        h('a', { class: 'btn', href: `#/planning/${encodeURIComponent(run.id)}` }, 'Plan a response from this run'))));
}

function tile(label, value, sub) {
  return h('article', { class: 'tile tile--sim' },
    h('div', { class: 'tile-label' }, label),
    h('div', { class: 'tile-value' }, value),
    h('div', { class: 'tile-sub' }, sub));
}

function hashShort(hex) {
  return short(hex || '', 12);
}

function hashCell(hex) {
  return h('span', { class: 'hash-row' }, h('span', { class: 'mono' }, hashShort(hex)), copyButton(hex || '', 'Copy full hash'));
}

function assumptionsView(assumptions) {
  const items = Array.isArray(assumptions) ? assumptions.map(String) : [];
  if (!items.length) return h('p', { class: 'muted' }, 'None reported.');
  return h('ul', { class: 'assumption-list' }, items.map((text) => h('li', null, text)));
}

// Vertical bars, one per hour, with the peak outlined. The table below carries the same numbers.
export function timelineChart(timeline, peakHour) {
  if (!timeline.length) return h('p', { class: 'muted' }, 'No timeline.');
  const points = sampleTimeline(timeline);
  const shares = barShares(points.map((p) => p.affected_rows));
  const W = 720;
  const H = 180;
  const pad = { t: 10, r: 8, b: 26, l: 40 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const slot = innerW / points.length;
  const barW = Math.max(2, slot * 0.7);
  const max = Math.max(0, ...points.map((p) => p.affected_rows));

  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', class: 'sim-chart',
    'aria-label': `Affected rows by hour, peak ${max} at hour ${peakHour}. The table below lists every hour.` });
  // Gridlines at 0, half and max.
  [0, 0.5, 1].forEach((f) => {
    const y = pad.t + innerH * (1 - f);
    svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y, y2: y, class: 'sim-grid' }));
    svg.append(svgEl('text', { x: pad.l - 6, y: y + 4, class: 'sim-axis', 'text-anchor': 'end' }, String(Math.round(max * f))));
  });
  points.forEach((p, i) => {
    const bh = innerH * shares[i];
    const x = pad.l + slot * i + (slot - barW) / 2;
    const isPeak = p.hour === peakHour;
    svg.append(svgEl('rect', { x, y: pad.t + innerH - bh, width: barW, height: Math.max(bh, 0),
      class: isPeak ? 'sim-bar sim-bar--peak' : 'sim-bar', rx: 2 }));
    if (i % Math.ceil(points.length / 8) === 0 || i === points.length - 1) {
      svg.append(svgEl('text', { x: x + barW / 2, y: H - 8, class: 'sim-axis', 'text-anchor': 'middle' }, `${p.hour}h`));
    }
  });
  return h('div', { class: 'sim-chart-wrap' }, svg);
}

function timelineTable(timeline) {
  return h('details', { class: 'sim-details' },
    h('summary', null, `Show all ${timeline.length} hours as a table`),
    h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Affected rows and road-blocked candidates by hour'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Hour'),
          h('th', { scope: 'col', class: 'num' }, 'Affected rows'),
          h('th', { scope: 'col', class: 'num' }, 'Road blocked candidates'),
          h('th', { scope: 'col', class: 'num' }, 'Unknown'))),
        h('tbody', null, timeline.map((p) => h('tr', null,
          h('td', null, `${p.hour} h`),
          h('td', { class: 'num' }, String(p.affected_rows)),
          h('td', { class: 'num' }, String(p.road_blocked_candidates)),
          h('td', { class: 'num' }, String(p.counts_by_severity.UNKNOWN || 0))))))));
}

export function perDistrictTable(perDistrict) {
  const rows = Object.entries(perDistrict || {}).sort((a, b) => b[1].affected_rows - a[1].affected_rows || a[0].localeCompare(b[0]));
  if (!rows.length) return h('p', { class: 'muted' }, 'No districts in this run.');
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, 'Peak snapshot by district'),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, 'District'),
        h('th', { scope: 'col', class: 'num' }, 'Rows'),
        h('th', { scope: 'col', class: 'num' }, 'Affected'),
        h('th', { scope: 'col', class: 'num' }, 'Road blocked candidates'),
        h('th', { scope: 'col', class: 'num' }, 'Top-severity rows'))),
      h('tbody', null, rows.map(([name, s]) => h('tr', null,
        h('td', { class: 'wrap-any' }, name),
        h('td', { class: 'num' }, String(s.rows)),
        h('td', { class: 'num' }, String(s.affected_rows)),
        h('td', { class: 'num' }, String(s.road_blocked_candidates)),
        h('td', { class: 'num' }, String(s.top_severity_rows)))))));
}

function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
  if (text !== undefined) el.textContent = text;
  return el;
}
