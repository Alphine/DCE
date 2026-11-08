import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox } from '../dom.js';
import { hasRole } from '../session.js';
import { barRow, gauge, num } from '../components/mini-charts.js';

// Logistics registry (SDD 15.1, 14.2): shelters, supply stock, teams and vehicles. Viewers read the lists.
// Analysts add records and change a shelter, team or vehicle status. The Resource Planner compares these with need.

const SHELTER_STATUS = ['OPEN', 'FULL', 'CLOSED'];
const AVAILABILITY = ['AVAILABLE', 'DEPLOYED', 'UNAVAILABLE'];
const TEAM_TYPES = ['RESCUE', 'MEDICAL', 'TRANSPORT'];
const SUPPLY_ITEMS = ['water_packs', 'food_packs', 'shelter_kits', 'medical_kits'];

const COUNTRY_FIELD = { name: 'country_code', label: 'Country (ISO code, optional)', maxlength: 2 };

export const KINDS = {
  shelters: {
    label: 'Shelters', singular: 'shelter', statuses: SHELTER_STATUS,
    columns: [
      { label: 'Name', get: (r) => r.name },
      { label: 'District', get: (r) => r.district },
      { label: 'Country', get: (r) => r.country_code },
      { label: 'Capacity (people)', get: (r) => r.capacity_people, num: true },
      { label: 'Status', get: (r) => r.status },
      { label: 'Updated', get: (r) => fmtDate(r.updated_at) },
    ],
    fields: [
      { name: 'name', label: 'Name', required: true, maxlength: 120 },
      { name: 'district', label: 'District', required: true, maxlength: 120 },
      COUNTRY_FIELD,
      { name: 'capacity_people', label: 'Capacity (people)', type: 'number', min: 0, required: true },
      { name: 'status', label: 'Status', options: SHELTER_STATUS, required: true },
    ],
  },
  supplies: {
    label: 'Supply stock', singular: 'supply count', statuses: null,
    columns: [
      { label: 'Shelter', get: (r) => r.shelter_name || '(no shelter)' },
      { label: 'District', get: (r) => r.district },
      { label: 'Item', get: (r) => r.item },
      { label: 'Quantity', get: (r) => r.quantity, num: true },
      { label: 'Updated', get: (r) => fmtDate(r.updated_at) },
    ],
    fields: [
      { name: 'shelter_id', label: 'Shelter', required: true, select: 'shelters' },
      { name: 'item', label: 'Item', options: SUPPLY_ITEMS, required: true },
      { name: 'quantity', label: 'Quantity on hand', type: 'number', min: 0, required: true },
    ],
  },
  teams: {
    label: 'Rescue and medical teams', singular: 'team', statuses: AVAILABILITY,
    columns: [
      { label: 'Type', get: (r) => r.team_type },
      { label: 'Size (people)', get: (r) => r.size, num: true },
      { label: 'District', get: (r) => r.district },
      { label: 'Country', get: (r) => r.country_code },
      { label: 'Status', get: (r) => r.status },
      { label: 'Updated', get: (r) => fmtDate(r.updated_at) },
    ],
    fields: [
      { name: 'team_type', label: 'Team type', options: TEAM_TYPES, required: true },
      { name: 'size', label: 'Size (people)', type: 'number', min: 1, required: true },
      { name: 'district', label: 'District', required: true, maxlength: 120 },
      COUNTRY_FIELD,
      { name: 'status', label: 'Status', options: AVAILABILITY, required: true },
    ],
  },
  vehicles: {
    label: 'Vehicles', singular: 'vehicle', statuses: AVAILABILITY,
    columns: [
      { label: 'Vehicle', get: (r) => r.vehicle_type },
      { label: 'Capacity (people)', get: (r) => r.capacity_people, num: true },
      { label: 'District', get: (r) => r.district },
      { label: 'Country', get: (r) => r.country_code },
      { label: 'Status', get: (r) => r.status },
      { label: 'Updated', get: (r) => fmtDate(r.updated_at) },
    ],
    fields: [
      { name: 'vehicle_type', label: 'Vehicle type', required: true, maxlength: 120 },
      { name: 'capacity_people', label: 'Capacity (people)', type: 'number', min: 0, required: true },
      { name: 'district', label: 'District', required: true, maxlength: 120 },
      COUNTRY_FIELD,
      { name: 'status', label: 'Status', options: AVAILABILITY, required: true },
    ],
  },
};

// Value for a cell. Numbers get locale grouping, and an empty value shows a dash.
export function cellText(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString();
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

// Builds the JSON body for a create form. Empty optional fields are left out, and numbers are converted.
export function bodyFromValues(fields, values) {
  const body = {};
  for (const field of fields) {
    const raw = String(values[field.name] ?? '').trim();
    if (raw === '') {
      if (field.required) throw new Error(`Fill in ${field.label.toLowerCase()}.`);
      continue;
    }
    body[field.name] = field.type === 'number' ? Number(raw) : raw;
  }
  return body;
}

export async function mount(root, ctx) {
  const { user, signal } = ctx;
  const canWrite = hasRole(user, 'Analyst');
  let tab = 'shelters';
  let filters = { country: '', district: '' };
  let shelters = [];

  root.append(pageHead('Logistics',
    'Shelters, supply stock, teams and vehicles by district. These are records entered by staff, not a verified inventory.'));

  const tabButtons = Object.entries(KINDS).map(([key, kind]) => h('button', {
    class: 'btn btn-sm', type: 'button', id: `lg-tab-${key}`, role: 'tab',
    'aria-selected': 'false', 'aria-controls': 'lg-panel', onclick: () => choose(key),
  }, kind.label));
  root.append(h('div', { class: 'row', role: 'tablist', 'aria-label': 'Logistics lists' }, tabButtons));

  root.append(filterBar());
  const body = h('div', { class: 'stack', id: 'lg-panel', role: 'tabpanel' });
  root.append(body);

  await loadShelters();
  choose(tab);

  function choose(key) {
    tab = key;
    tabButtons.forEach((btn, i) => {
      const selected = Object.keys(KINDS)[i] === key;
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
      btn.classList.toggle('btn-primary', selected);
    });
    body.setAttribute('aria-labelledby', `lg-tab-${key}`);
    load();
  }

  function filterBar() {
    const country = h('input', { id: 'lg-country', maxlength: 2, value: filters.country, autocomplete: 'off' });
    const district = h('input', { id: 'lg-district', maxlength: 120, value: filters.district, autocomplete: 'off' });
    const err = h('div', { 'aria-live': 'polite' });
    return h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Filter logistics lists',
      onsubmit: (e) => {
        e.preventDefault();
        filters = { country: country.value.trim(), district: district.value.trim() };
        load();
      } },
    h('div', { class: 'field' }, h('label', { for: 'lg-country' }, 'Country (ISO code)'), country),
    h('div', { class: 'field' }, h('label', { for: 'lg-district' }, 'District'), district),
    err,
    h('div', { class: 'field--wide row' }, h('button', { class: 'btn', type: 'submit' }, 'Apply filters')));
  }

  async function loadShelters() {
    if (!canWrite) return;
    try {
      shelters = listOf(await api.get('logistics/shelters', { signal }));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      shelters = [];
    }
  }

  async function load() {
    const kind = KINDS[tab];
    body.replaceChildren(panel({ title: kind.label, style: '--i:1' }, spinner(`Loading ${kind.label.toLowerCase()}…`)));
    const query = new URLSearchParams();
    if (filters.country) query.set('country', filters.country);
    if (filters.district) query.set('district', filters.district);
    const qs = query.toString() ? `?${query}` : '';
    try {
      const rows = listOf(await api.get(`logistics/${tab}${qs}`, { signal }));
      if (signal.aborted) return;
      body.replaceChildren(listPanel(kind, rows), canWrite ? addPanel(kind) : roleNote(kind));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      body.replaceChildren(panel({ title: kind.label, style: '--i:1' }, errorState(err, load)));
    }
  }

  function listPanel(kind, rows) {
    const sub = rows.length >= 500 ? 'Newest first. Showing the first 500 rows.' : 'Newest first.';
    if (!rows.length) {
      return panel({ title: kind.label, sub, style: '--i:1' },
        emptyState(`No ${kind.label.toLowerCase()} yet`, canWrite ? 'Add one with the form below.' : 'An Analyst adds records here.',
          { icon: 'logistics', actions: [{ label: 'Open Situation', href: '#/situation' }] }));
    }
    const head = kind.columns.map((c) => h('th', { scope: 'col', class: c.num ? 'num' : null }, c.label));
    if (canWrite && kind.statuses) head.push(h('th', { scope: 'col' }, 'Change status'));
    return panel({ title: kind.label, sub, style: '--i:1' },
      kind === KINDS.supplies ? supplySummary(rows) : null,
      h('div', { class: 'table-wrap' },
        h('table', { class: 'table' },
          h('caption', { class: 'sr-only' }, kind.label),
          h('thead', null, h('tr', null, head)),
          h('tbody', null, rows.map((row) => h('tr', null,
            kind.columns.map((c) => h('td', { class: c.num ? 'num mono' : 'wrap-any' }, cellText(c.get(row)))),
            canWrite && kind.statuses ? h('td', null, statusEditor(kind, row)) : null))))));
  }

  // Stock per standard item as bars, and how many of the standard items have any stock recorded (gauge).
  // The rows here carry no need figure, so bars are scaled to the largest stock. Need is compared on the Resources screen.
  function supplySummary(rows) {
    const totals = SUPPLY_ITEMS.map((item) => rows.reduce((sum, r) => (
      r.item === item ? sum + (num(r.quantity) || 0) : sum), 0));
    const top = Math.max(0, ...totals);
    const covered = totals.filter((t) => t > 0).length;
    const pct = (covered / SUPPLY_ITEMS.length) * 100;
    return h('div', { class: 'mc-summary' },
      h('div', { class: 'mc-summary-gauge' },
        gauge(pct, { label: 'Standard items with stock recorded', tone: covered === SUPPLY_ITEMS.length ? 'LOW' : 'HIGH' }),
        h('p', { class: 'small' },
          `${covered} of ${SUPPLY_ITEMS.length} standard items have stock in these rows. Need is not shown here.`)),
      h('div', { class: 'mc-summary-bars', role: 'group', 'aria-label': 'Stock on hand by item' },
        SUPPLY_ITEMS.map((item, i) => barRow({
          label: item.replace(/_/g, ' '),
          value: totals[i],
          max: top,
        }))));
  }

  // Changes a status with PATCH. Only shelters, teams and vehicles have one.
  function statusEditor(kind, row) {
    const select = h('select', { 'aria-label': `New status for ${kind.singular} ${row.id}` },
      kind.statuses.map((s) => h('option', { value: s }, s)));
    select.value = row.status;
    const note = h('span', { role: 'status', class: 'muted small' });
    const save = h('button', { class: 'btn btn-sm', type: 'button', onclick: async () => {
      save.disabled = true;
      note.textContent = '';
      try {
        await api.patch(`logistics/${tab}/${row.id}`, { status: select.value }, { signal });
        if (!signal.aborted) load();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        note.textContent = err.message;
        save.disabled = false;
      }
    } }, 'Save');
    return h('div', { class: 'row' }, select, save, note);
  }

  function roleNote(kind) {
    return panel({ title: `Add ${kind.singular}`, style: '--i:2' },
      alertBox('info', 'An Analyst adds and updates records. You can read this list.'));
  }

  function addPanel(kind) {
    const err = h('div', { 'aria-live': 'polite' });
    const controls = kind.fields.map((field) => ({ field, input: fieldControl(field) }));
    const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, `Add ${kind.singular}`);
    const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': `Add ${kind.singular}`,
      onsubmit: async (e) => {
        e.preventDefault();
        err.replaceChildren();
        let body;
        try {
          body = bodyFromValues(kind.fields, Object.fromEntries(controls.map((c) => [c.field.name, c.input.value])));
        } catch (validation) {
          err.replaceChildren(alertBox('error', validation.message));
          return;
        }
        submit.disabled = true;
        try {
          await api.post(`logistics/${tab}`, body, { signal });
          if (signal.aborted) return;
          if (tab === 'shelters') await loadShelters();
          load();
        } catch (apiErr) {
          if (signal.aborted || apiErr.name === 'AbortError') return;
          err.replaceChildren(alertBox('error', apiErr.message));
          submit.disabled = false;
        }
      } },
    controls.map((c) => h('div', { class: 'field' }, h('label', { for: c.input.id }, c.field.label), c.input)),
    err,
    h('div', { class: 'field--wide row' }, submit));
    return panel({ title: `Add ${kind.singular}`, sub: 'Analyst role.', style: '--i:2' }, form);
  }

  function fieldControl(field) {
    const id = `lg-f-${tab}-${field.name}`;
    if (field.select === 'shelters') {
      const select = h('select', { id },
        h('option', { value: '' }, shelters.length ? 'Choose a shelter' : 'Add a shelter first'),
        shelters.map((s) => h('option', { value: s.id }, `${s.name} (${s.district})`)));
      return select;
    }
    if (field.options) {
      return h('select', { id }, field.options.map((o) => h('option', { value: o }, o)));
    }
    return h('input', { id, name: field.name, type: field.type || 'text', min: field.min, maxlength: field.maxlength,
      required: field.required ? true : null, autocomplete: 'off' });
  }
}
