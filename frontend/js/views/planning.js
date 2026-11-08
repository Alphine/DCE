import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv, short } from '../dom.js';
import { dataClassBadge } from '../components/badges.js';
import { copyButton } from '../components/copy.js';
import { go } from '../router.js';
import { hasRole } from '../session.js';

// Response planning (SDD 15.1). Allocations come from a stored simulation run and the flood pack ratios.
// The server computes them. This screen only shows them. Nothing here is saved, approved or executed.
// To act on a plan, an Analyst proposes a mission (SDD 15.2), and an Approver decides it (SDD 15.4).

export const TOTAL_KEYS = [
  ['households_affected', 'Households affected'],
  ['people_estimated', 'People estimated'],
  ['water_packs', 'Water packs'],
  ['food_packs', 'Food packs'],
  ['shelter_kits', 'Shelter kits'],
  ['drinking_water_litres', 'Drinking water (litres)'],
];

// Sorts plan rows by their rank, so a plan always shows priority 1 first.
export function rankedRows(allocations) {
  return (Array.isArray(allocations) ? allocations : [])
    .slice()
    .sort((a, b) => a.priority_rank - b.priority_rank);
}

export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;

  root.append(pageHead('Planning',
    'Resource allocation for each district, from a simulation run. Illustrative only, and not an approved plan.'));

  const pickSlot = h('div', { class: 'stack' }, spinner('Loading runs…'));
  const planSlot = h('div', { class: 'stack' });
  root.append(panel({ title: 'Basis', sub: 'Choose the simulation run this plan uses.', style: '--i:1' }, pickSlot));
  root.append(planSlot);

  await loadRuns();

  async function loadRuns() {
    try {
      const runs = listOf(await api.get('simulations', { signal }));
      if (signal.aborted) return;
      showRuns(runs);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      pickSlot.replaceChildren(errorState(err, loadRuns));
    }
  }

  function showRuns(runs) {
    if (!runs.length) {
      pickSlot.replaceChildren(emptyState('No simulation runs yet',
        hasRole(user, 'Analyst')
          ? 'A plan needs a simulation run first. Create one on the Simulation screen.'
          : 'An Analyst needs to run a simulation before a plan can be shown.'),
        h('div', { class: 'row' }, h('a', { class: 'btn', href: '#/simulation' }, 'Go to Simulation')));
      return;
    }

    const activeId = selectedId && runs.some((r) => r.id === selectedId) ? selectedId : runs[0].id;
    const select = h('select', { id: 'pl-run', 'aria-describedby': 'pl-run-hint' },
      runs.map((r) => h('option', { value: r.id },
        `${r.name} · ${(r.dataset && r.dataset.name) || 'dataset'} · ${fmtDate(r.created_at)}`)));
    select.value = activeId;
    select.addEventListener('change', () => go(`#/planning/${encodeURIComponent(select.value)}`));
    pickSlot.replaceChildren(
      h('div', { class: 'field' }, h('label', { for: 'pl-run' }, 'Simulation run'), select),
      h('p', { class: 'small muted', id: 'pl-run-hint' }, 'Plans use the peak hour of the chosen run. Changing the run shows its plan.'));

    renderPlan(activeId);
  }

  async function renderPlan(id) {
    planSlot.replaceChildren(panel({ title: 'Allocation', style: '--i:2' }, spinner('Computing the allocation…')));
    try {
      const plan = await api.get(`planning/allocation?simulation_id=${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      planSlot.replaceChildren(planView(plan));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      planSlot.replaceChildren(panel({ title: 'Allocation', style: '--i:2' }, errorState(err, () => renderPlan(id))));
    }
  }
}

export function planView(plan) {
  const basis = plan.basis || {};
  const totals = plan.totals || {};
  const rows = rankedRows(plan.allocations);
  const tiles = h('div', { class: 'tiles' }, TOTAL_KEYS.map(([key, label], i) =>
    h('article', { class: 'tile tile--sim', style: `--i:${i}` },
      h('div', { class: 'tile-label' }, label),
      h('div', { class: 'tile-value' }, (totals[key] || 0).toLocaleString()),
      h('div', { class: 'tile-sub' }, 'All ranked districts'))));

  return h('div', { class: 'stack' },
    panel({ title: 'Allocation', sub: `From "${basis.simulation ? basis.simulation.name : 'simulation'}" at hour ${basis.peak_hour ?? '—'}`,
      actions: [dataClassBadge('SIMULATED_FACT')], style: '--i:2' },
      alertBox('warn', 'Illustrative allocation, not for operational use. Ratios come from the flood pack and are not validated.'),
      tiles,
      rows.length
        ? h('div', { class: 'table-wrap' },
          h('table', { class: 'table' },
            h('caption', { class: 'sr-only' }, 'Allocation by district, in priority order'),
            h('thead', null, h('tr', null,
              h('th', { scope: 'col', class: 'num' }, 'Priority'),
              h('th', { scope: 'col' }, 'District'),
              h('th', { scope: 'col', class: 'num' }, 'Households'),
              h('th', { scope: 'col', class: 'num' }, 'People'),
              h('th', { scope: 'col', class: 'num' }, 'Water packs'),
              h('th', { scope: 'col', class: 'num' }, 'Food packs'),
              h('th', { scope: 'col', class: 'num' }, 'Shelter kits'),
              h('th', { scope: 'col', class: 'num' }, 'Drinking water (L)'))),
            h('tbody', null, rows.map((r) => h('tr', null,
              h('td', { class: 'num' }, h('span', { class: 'priority-pill' }, String(r.priority_rank))),
              h('td', { class: 'wrap-any' }, r.district),
              h('td', { class: 'num' }, String(r.households_affected)),
              h('td', { class: 'num' }, String(r.people_estimated)),
              h('td', { class: 'num' }, String(r.water_packs)),
              h('td', { class: 'num' }, String(r.food_packs)),
              h('td', { class: 'num' }, String(r.shelter_kits)),
              h('td', { class: 'num' }, String(r.drinking_water_litres)))))))
        : emptyState('No district needs an allocation',
          'Nothing in this run reaches the affected depth at its peak hour. Try a higher depth multiplier or horizon.'),
      h('p', { class: 'small muted' }, districtNote(plan.districts_without_need || 0, rows.length))),
    panel({ title: 'Not estimated', sub: 'These items need data the flood pack does not hold, so no number is given.', style: '--i:3' },
      h('ul', { class: 'assumption-list' }, (plan.not_estimated || []).map((item) => h('li', null, item)))),
    panel({ title: 'Assumptions', style: '--i:4' },
      h('ul', { class: 'assumption-list' }, (plan.assumptions || []).map((text) => h('li', null, text)))),
    panel({ title: 'Basis and next step', sub: 'Check the basis before acting on any figure.', style: '--i:5' },
      h('dl', { class: 'kv-list' },
        kv('Simulation', basis.simulation ? basis.simulation.name : '—'),
        kv('Peak hour', String(basis.peak_hour ?? '—')),
        kv('Output hash', hashCell(basis.output_sha256)),
        kv('Rule pack', basis.rule_pack ? `${basis.rule_pack.pack_id} · ${short(basis.rule_pack.sha256, 12)}` : '—')),
      h('div', { class: 'row' },
        h('a', { class: 'btn btn-primary', href: '#/missions' }, 'Propose a mission'),
        h('a', { class: 'btn', href: '#/simulation' }, 'Open Simulation'))));
}

// Explains who is left out, in words that fit both the empty and the full case.
export function districtNote(withoutNeed, ranked) {
  if (withoutNeed === 0) return ranked ? 'Every district in this run has affected rows at peak.' : '';
  const noun = withoutNeed === 1 ? 'district has' : 'districts have';
  return `${withoutNeed} ${noun} no affected rows at peak, so they get no allocation.`;
}

function hashCell(hex) {
  return h('span', { class: 'hash-row' }, h('span', { class: 'mono' }, short(hex || '', 12)), copyButton(hex || '', 'Copy full hash'));
}
