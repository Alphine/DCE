import { api } from '../api.js';
import { h, fmtDate, fmtBytes, short, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { datasetStatusBadge, dataClassBadge } from '../components/badges.js';
import { copyButton } from '../components/copy.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { can, isOwner, hasRole } from '../session.js';
import { loadList, cacheNotice } from '../offline/read-cache.js';

const MAX_BYTES = 10 * 1024 * 1024; // 10 MB, matches docs/api.md §3
const ACCEPTED_NAME = /\.(csv|geojson|json)$/i; // backend: .csv is CSV, anything else is GeoJSON
const MAP_ROWS = 1000; // docs/api.md: maximum limit on /rows
const PREVIEW_CAP = 5;
const SVG_NS = 'http://www.w3.org/2000/svg';
const STATUS_FILTERS = [
  ['ALL', 'All statuses'],
  ['PENDING_VALIDATION', 'Pending'],
  ['APPROVED', 'Approved'],
  ['REJECTED', 'Rejected'],
];

// ---- Pure helpers (no DOM, so they can be checked in Node) ----

export function validateDatasetFile(file) {
  if (!file) return 'Choose a file first.';
  if (!ACCEPTED_NAME.test(file.name)) return 'Only CSV or GeoJSON files are accepted.';
  if (file.size === 0) return 'The file is empty.';
  if (file.size > MAX_BYTES) return `The file is ${fmtBytes(file.size)}. The limit is 10 MB.`;
  return null;
}

// The country code is optional. Blank means the server default applies.
export function validateCountry(code) {
  const v = String(code || '').trim();
  if (!v) return null;
  return /^[A-Za-z]{2}$/.test(v) ? null : 'Country code must be two letters, for example ID.';
}

export function kindLabel(kind) {
  if (kind === 'CSV') return 'CSV';
  if (kind === 'GEOJSON') return 'GeoJSON';
  return kind || '—';
}

// Share of null cells in one column, as a whole percentage. Null when the row count is unknown.
export function nullShare(nulls, rows) {
  if (!Number.isFinite(nulls) || !Number.isFinite(rows) || rows <= 0) return null;
  return Math.round((nulls / rows) * 100);
}

// True when the profile has both a lat and a lon column (case-insensitive).
export function hasCoordinateColumns(columns) {
  const names = new Set((Array.isArray(columns) ? columns : []).map((c) => String(c && c.name).toLowerCase()));
  return names.has('lat') && names.has('lon');
}

// Places rows with finite lat/lon on a local equirectangular plane (degrees, north up).
// Nothing is invented: rows without valid coordinates are skipped.
// Returns null when no row can be placed.
export function planarPoints(rows) {
  const valid = (Array.isArray(rows) ? rows : []).filter((r) => r
    && Number.isFinite(r.lat) && Number.isFinite(r.lon)
    && Math.abs(r.lat) <= 90 && Math.abs(r.lon) <= 180);
  if (!valid.length) return null;
  const lat0 = valid.reduce((sum, r) => sum + r.lat, 0) / valid.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const points = valid.map((r) => ({ id: r.id ?? '', lat: r.lat, lon: r.lon, x: r.lon * k, y: -r.lat }));
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const MIN_SPAN = 0.02; // degrees, so one point or a tight cluster still has a visible frame
  const w = Math.max(Math.max(...xs) - Math.min(...xs), MIN_SPAN);
  const hgt = Math.max(Math.max(...ys) - Math.min(...ys), MIN_SPAN);
  const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
  const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
  const pad = Math.max(w, hgt) * 0.12;
  return {
    points,
    view: { x: cx - w / 2 - pad, y: cy - hgt / 2 - pad, width: w + 2 * pad, height: hgt + 2 * pad },
  };
}

// Items from a usage lookup: which simulations and missions read this dataset.
export function usageFor(datasetId, simulations, missions) {
  const sims = (Array.isArray(simulations) ? simulations : [])
    .filter((s) => s && s.dataset && s.dataset.id === datasetId);
  const mis = (Array.isArray(missions) ? missions : [])
    .filter((m) => m && m.source && m.source.type === 'DATASET' && m.source.id === datasetId);
  return { simulations: sims, missions: mis };
}

// ---- DOM helpers ----

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  for (const child of children) if (child) node.append(child);
  return node;
}

// ctx: { user, params, signal, navigate }
export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;
  const listSlot = h('div', null, spinner('Loading datasets…'));
  const detailSlot = h('div', { class: 'stack ds-detail' });
  let datasets = [];
  let statusFilter = 'ALL';

  const parts = [
    pageHead('Datasets',
      'Upload CSV or GeoJSON incident data, then a reviewer approves it. The agent can only use approved datasets.'),
  ];
  if (can.upload(user)) parts.push(uploadPanel());
  parts.push(panel({ title: 'All datasets', sub: 'Newest first. Open a row for its profile.', style: '--i:2', cls: 'ds-list-panel' }, listSlot));
  parts.push(detailSlot);
  root.append(...parts);

  async function refreshList() {
    try {
      const res = await loadList('datasets', 'datasets', { signal });
      if (signal.aborted) return;
      datasets = res.items;
      renderList();
      if (res.savedAt) listSlot.prepend(cacheNotice(res.savedAt));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, refreshList));
    }
  }

  function statusSelect() {
    const select = h('select', { id: 'ds-status-filter', 'aria-label': 'Filter datasets by status' },
      STATUS_FILTERS.map(([value, label]) => h('option', { value, selected: value === statusFilter }, label)));
    select.addEventListener('change', () => {
      statusFilter = select.value;
      renderList();
    });
    return select;
  }

  function renderList() {
    const filterWrap = h('div', { class: 'ds-filter' },
      h('label', { class: 'label', for: 'ds-status-filter' }, 'Status'), statusSelect());
    if (!datasets.length) {
      listSlot.replaceChildren(emptyState('No datasets yet', hasRole(user, 'Analyst') ? 'Upload a CSV or GeoJSON file above to start.' : 'An analyst needs to upload one.',
        { icon: 'datasets', actions: [{ label: 'Open Reports', href: '#/reports' }] }));
      return;
    }
    const sorted = [...datasets].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const shown = statusFilter === 'ALL' ? sorted : sorted.filter((d) => d.status === statusFilter);
    const body = shown.length
      ? h('div', { class: 'table-wrap' },
          h('table', { class: 'table ds-table' },
            h('caption', { class: 'sr-only' }, 'Datasets'),
            h('thead', null, h('tr', null,
              h('th', { scope: 'col' }, 'Name'),
              h('th', { scope: 'col' }, 'File'),
              h('th', { scope: 'col' }, 'Kind'),
              h('th', { scope: 'col' }, 'Country'),
              h('th', { scope: 'col', class: 'num' }, 'Size'),
              h('th', { scope: 'col' }, 'Status'),
              h('th', { scope: 'col' }, 'Uploaded by'),
              h('th', { scope: 'col' }, 'Uploaded'))),
            h('tbody', null, shown.map((d) => h('tr', { class: 'row-link' },
              h('td', { class: 'wrap-any' }, h('a', { href: `#/datasets/${encodeURIComponent(d.id)}` }, d.name || d.filename)),
              h('td', { class: 'mono wrap-any' }, d.filename),
              h('td', null, h('span', { class: 'ds-kind' }, kindLabel(d.kind))),
              h('td', null, h('span', { class: 'ds-code mono' }, d.country_code || '—')),
              h('td', { class: 'num' }, fmtBytes(d.size_bytes)),
              h('td', null, datasetStatusBadge(d.status)),
              h('td', null, (d.owner && d.owner.username) || '—'),
              h('td', null, fmtDate(d.created_at)))))))
      : emptyState('No datasets with this status', 'Choose All statuses to see every dataset.');
    listSlot.replaceChildren(filterWrap, body);
  }

  // Upload: drag and drop plus file picker, with client-side checks. The server checks again.
  function uploadPanel() {
    const nameInput = h('input', { id: 'ds-name', type: 'text', maxlength: '120', placeholder: 'Optional. Defaults to the file name' });
    const countryInput = h('input', { id: 'ds-country', type: 'text', maxlength: '2', autocomplete: 'off', placeholder: 'Optional, for example ID', class: 'ds-country-input' });
    const picked = h('p', { class: 'small muted', 'aria-live': 'polite' }, 'No file chosen. CSV or GeoJSON, up to 10 MB.');
    const errorSlot = h('div');
    const submit = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Upload dataset');
    const fileInput = h('input', { id: 'ds-file', type: 'file', accept: '.csv,.geojson,.json,text/csv,application/geo+json,application/json', class: 'sr-only' });
    const zone = h('div', { class: 'dropzone', tabindex: '-1' },
      h('div', { class: 'dropzone-glyph', 'aria-hidden': 'true' }, '↓'),
      h('p', null, h('strong', null, 'Drop a file here'), ' or'),
      h('label', { class: 'btn btn-sm', for: 'ds-file' }, 'Choose file'),
      picked);
    let file = null;

    function setFile(f) {
      file = f || null;
      errorSlot.replaceChildren();
      const problem = validateDatasetFile(file);
      if (problem) {
        errorSlot.replaceChildren(alertBox('error', problem));
        file = null;
        picked.textContent = 'No file chosen. CSV or GeoJSON, up to 10 MB.';
        zone.classList.remove('has-file');
      } else {
        picked.textContent = `${file.name} · ${fmtBytes(file.size)}`;
        zone.classList.add('has-file');
      }
      submit.disabled = !file;
    }

    fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.add('is-over');
    }));
    ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.remove('is-over');
    }));
    zone.addEventListener('drop', (e) => {
      const dropped = e.dataTransfer && e.dataTransfer.files[0];
      if (dropped) setFile(dropped);
    });

    async function onSubmit(event) {
      event.preventDefault();
      if (!file) return;
      const country = countryInput.value.trim().toUpperCase();
      const countryProblem = validateCountry(country);
      if (countryProblem) {
        errorSlot.replaceChildren(alertBox('error', countryProblem));
        return;
      }
      submit.disabled = true;
      submit.textContent = 'Uploading…';
      try {
        const fd = new FormData();
        fd.append('file', file, file.name);
        const name = nameInput.value.trim();
        if (name) fd.append('name', name);
        if (country) fd.append('country_code', country);
        const created = await api.upload('datasets', fd, { signal });
        if (signal.aborted) return;
        toast('Dataset uploaded. A reviewer must approve it before the agent can use it.', { kind: 'success' });
        if (created && created.id) go(`#/datasets/${encodeURIComponent(created.id)}`);
        else refreshList();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        errorSlot.replaceChildren(alertBox('error', err.message));
        toast(err.message, { kind: 'error' });
      } finally {
        submit.textContent = 'Upload dataset';
        submit.disabled = !file;
      }
    }

    return panel({ title: 'Upload dataset', sub: 'Analyst role or higher. A new upload waits for a reviewer.', style: '--i:1', cls: 'ds-upload-panel' },
      h('form', { class: 'ds-upload', onsubmit: onSubmit, 'aria-label': 'Upload dataset' },
        h('div', { class: 'field-row' },
          h('div', { class: 'field' },
            h('label', { class: 'label', for: 'ds-name' }, 'Display name'),
            nameInput),
          h('div', { class: 'field' },
            h('label', { class: 'label', for: 'ds-country' }, 'Country code'),
            countryInput,
            h('span', { class: 'hint' }, 'Two letters. Blank uses the server default.'))),
        h('div', { class: 'field' },
          h('span', { class: 'label' }, 'File'),
          zone,
          fileInput),
        errorSlot,
        h('div', { class: 'row' }, submit,
          h('span', { class: 'hint' }, 'CSV or GeoJSON, up to 10 MB. The file is checked again on the server.'))));
  }

  // Detail: metadata, approval, profile, preview, map, and usage.
  async function loadDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Dataset detail', style: '--i:3' }, spinner('Loading dataset…')));
    try {
      const ds = await api.get(`datasets/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      renderDetail(ds);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Dataset detail' }, errorState(err, () => loadDetail(id))));
    }
  }

  function decisionControls(ds) {
    const pending = ds.status === 'PENDING_VALIDATION';
    const enc = encodeURIComponent(ds.id);
    const msg = h('div', { 'aria-live': 'polite' });
    const approveBtn = h('button', { class: 'btn btn-primary btn-gate', type: 'button' }, 'Approve dataset');
    const rejectBtn = h('button', { class: 'btn btn-danger', type: 'button' }, 'Reject dataset');
    const actionRow = h('div', { class: 'row' }, approveBtn, rejectBtn);
    const noteInput = h('textarea', { id: 'ds-reject-note', maxlength: '500', rows: '3' });
    const noteField = h('div', { class: 'field ds-reject-note', hidden: true },
      h('label', { class: 'label', for: 'ds-reject-note' }, 'Reason for rejection (optional, max 500 characters)'),
      noteInput);
    const confirmBtn = h('button', { class: 'btn btn-primary', type: 'button' }, 'Confirm');
    const cancelBtn = h('button', { class: 'btn btn-ghost', type: 'button' }, 'Cancel');
    const confirmRow = h('div', { class: 'stack ds-confirm', hidden: true }, noteField, h('div', { class: 'row' }, confirmBtn, cancelBtn));
    let mode = null;

    // Two-step: the first press opens the confirm row, the second sends the request.
    function setMode(next, focusTarget) {
      mode = next;
      actionRow.hidden = next !== null;
      confirmRow.hidden = next === null;
      noteField.hidden = next !== 'reject';
      confirmBtn.textContent = next === 'reject' ? 'Confirm rejection' : 'Confirm approval';
      confirmBtn.className = next === 'reject' ? 'btn btn-danger' : 'btn btn-primary';
      msg.replaceChildren();
      if (focusTarget) focusTarget.focus();
    }

    approveBtn.addEventListener('click', () => setMode('approve', confirmBtn));
    rejectBtn.addEventListener('click', () => setMode('reject', noteInput));
    cancelBtn.addEventListener('click', () => setMode(null, approveBtn));

    async function submitDecision() {
      if (!mode) return;
      const action = mode;
      confirmBtn.disabled = true;
      confirmBtn.textContent = action === 'reject' ? 'Rejecting…' : 'Approving…';
      try {
        if (action === 'approve') {
          await api.postEmpty(`datasets/${enc}/approve`, { signal });
        } else {
          const note = noteInput.value.trim();
          await api.post(`datasets/${enc}/reject`, note ? { note } : {}, { signal });
        }
        if (signal.aborted) return;
        toast(action === 'approve' ? 'Dataset approved.' : 'Dataset rejected.', { kind: 'success' });
        await loadDetail(ds.id);
        refreshList();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        // SELF_APPROVAL_NOT_ALLOWED and INVALID_STATE arrive here: show the server message inline and in a toast.
        msg.replaceChildren(alertBox('error', err.message));
        toast(err.message, { kind: 'error' });
        confirmBtn.textContent = action === 'reject' ? 'Confirm rejection' : 'Confirm approval';
      } finally {
        confirmBtn.disabled = false;
      }
    }
    confirmBtn.addEventListener('click', submitDecision);

    const wrap = h('div', { class: 'stack ds-decision' });
    if (!pending) {
      wrap.append(alertBox(ds.status === 'APPROVED' ? 'ok' : 'warn',
        ds.status === 'APPROVED'
          ? 'Approved. The agent can use this dataset.'
          : `Status: ${ds.status}. Only approved datasets can be used by the agent.`));
    } else if (can.approveDataset(user, ds)) {
      wrap.append(
        h('p', { class: 'hint' }, 'Approving lets the agent use this dataset. Rejecting keeps it out. You cannot decide on a dataset you uploaded.'),
        actionRow, confirmRow, msg);
    } else if (isOwner(user, ds)) {
      wrap.append(alertBox('info', 'You uploaded this dataset. Another reviewer must approve or reject it.'));
    } else {
      wrap.append(alertBox('info', 'Approval needs the Reviewer role. Ask a reviewer to approve or reject this dataset.'));
    }
    return wrap;
  }

  function renderDetail(ds) {
    const profile = ds.profile || {};
    const columns = Array.isArray(profile.columns) ? profile.columns : [];
    const preview = Array.isArray(profile.preview) ? profile.preview : [];
    const rows = Number.isFinite(profile.rows) ? profile.rows : null;
    const mapSlot = h('div');
    const usageSlot = h('div', { class: 'stack' });
    const mapPanelNeeded = hasCoordinateColumns(columns) && ds.kind !== 'GEOJSON';

    const code = ds.country_code || null;
    const profileTable = columns.length
      ? h('div', { class: 'table-wrap' },
          h('table', { class: 'table' },
            h('caption', { class: 'sr-only' }, 'Column profile'),
            h('thead', null, h('tr', null,
              h('th', { scope: 'col' }, 'Column'),
              h('th', { scope: 'col' }, 'Type'),
              h('th', { scope: 'col', class: 'num' }, 'Nulls'),
              h('th', { scope: 'col', class: 'num' }, 'Null share'))),
            h('tbody', null, columns.map((c) => {
              const share = nullShare(c.nulls, rows);
              return h('tr', null,
                h('td', { class: 'mono wrap-any' }, c.name),
                h('td', { class: 'mono' }, c.dtype),
                h('td', { class: 'num' }, String(c.nulls ?? 0)),
                h('td', { class: 'num' }, share === null ? '—' : `${share}%`));
            }))))
      : emptyState('No column profile', 'The server returned no columns for this dataset.');

    const previewRows = preview.slice(0, PREVIEW_CAP);
    const previewBlock = previewRows.length
      ? h('div', { class: 'table-wrap' }, previewTable(columns, previewRows))
      : emptyState('No preview rows', 'The dataset has no preview rows.');

    detailSlot.replaceChildren(panel({
      title: ds.name || ds.filename,
      sub: `${ds.filename} · ${kindLabel(ds.kind)} · ${fmtBytes(ds.size_bytes)} · uploaded ${fmtDate(ds.created_at)}`,
      actions: [datasetStatusBadge(ds.status), dataClassBadge('RAW_REPORT'), code ? h('span', { class: 'ds-code mono', title: 'Country code' }, code) : null],
      style: '--i:3',
    },
      h('dl', { class: 'kv-grid' },
        kv('Rows', rows ?? '—'),
        kv('Columns', columns.length || '—'),
        kv('Country', code || '—'),
        kv('Kind', kindLabel(ds.kind)),
        kv('Owner', (ds.owner && ds.owner.username) || '—'),
        h('div', { class: 'kv' }, h('dt', null, 'SHA-256'),
          h('dd', { class: 'hash-row' },
            h('span', { class: 'hash', title: ds.sha256 || '' }, short(ds.sha256, 24)),
            ds.sha256 ? copyButton(ds.sha256, 'Copy dataset SHA-256') : null))),
      h('div', { class: 'stack', style: 'margin-top:16px' }, decisionControls(ds)),
      h('h3', { class: 'ds-sub' }, 'Profile'),
      profileTable,
      h('h3', { class: 'ds-sub' }, 'Data class'),
      h('p', { class: 'hint' }, 'Uploaded files are RAW_REPORT: the original input, unmodified. Derived results (hazard runs, simulations) carry their own class.'),
      h('h3', { class: 'ds-sub' }, 'Preview'),
      previewBlock,
      h('p', { class: 'hint', style: 'margin-top:10px' }, `Showing up to ${PREVIEW_CAP} rows of ${rows ?? 'unknown'} from the server profile.`),
      mapPanelNeeded ? h('h3', { class: 'ds-sub' }, 'Map preview') : null,
      mapPanelNeeded ? mapSlot : null,
      h('h3', { class: 'ds-sub' }, 'Used by'),
      usageSlot));

    if (mapPanelNeeded) renderMap(ds, mapSlot);
    renderUsage(ds, usageSlot);
  }

  function previewTable(columns, rows) {
    const names = columns.length ? columns.map((c) => c.name) : Object.keys(rows[0] || {});
    return h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, 'Dataset preview'),
      h('thead', null, h('tr', null, names.map((n) => h('th', { scope: 'col', class: 'mono' }, n)))),
      h('tbody', null, rows.map((r) => h('tr', null, names.map((n) => h('td', { class: 'mono' }, r[n] === null || r[n] === undefined ? '∅' : String(r[n])))))));
  }

  // Map preview: only for approved datasets (or the uploader), since the rows endpoint refuses others.
  async function renderMap(ds, slot) {
    const canRead = ds.status === 'APPROVED' || isOwner(user, ds);
    if (!canRead) {
      slot.replaceChildren(alertBox('info', 'Coordinates are shown after a reviewer approves this dataset.'));
      return;
    }
    slot.replaceChildren(spinner('Placing points…'));
    try {
      const res = await api.get(`datasets/${encodeURIComponent(ds.id)}/rows?limit=${MAP_ROWS}&offset=0`, { signal });
      if (signal.aborted) return;
      const items = listOf(res);
      const plane = planarPoints(items);
      const total = res && Number.isFinite(res.total) ? res.total : items.length;
      if (!plane) {
        slot.replaceChildren(emptyState('No valid coordinates', 'Rows have no usable lat and lon values, so nothing is plotted.'));
        return;
      }
      const { view, points } = plane;
      const radius = Math.max(view.width, view.height) / 90;
      const svg = svgEl('svg', {
        class: 'ds-map-svg',
        viewBox: `${view.x} ${view.y} ${view.width} ${view.height}`,
        preserveAspectRatio: 'xMidYMid meet',
        role: 'img',
        'aria-label': `Plot of ${points.length} rows with coordinates`,
      },
        svgEl('rect', { class: 'ds-map-frame', x: view.x, y: view.y, width: view.width, height: view.height }),
        ...points.map((p) => svgEl('circle', { class: 'ds-map-dot', cx: p.x, cy: p.y, r: radius },
          svgEl('title', {}, document.createTextNode(`${p.id ? `${p.id} · ` : ''}${p.lat}, ${p.lon}`)))));
      const truncated = res && res.next_offset !== null && res.next_offset !== undefined;
      slot.replaceChildren(
        h('div', { class: 'ds-map' }, svg),
        h('p', { class: 'hint' },
          `Plotted ${points.length} of ${total} rows with coordinates${truncated ? `. Only the first ${MAP_ROWS} rows are drawn` : ''}. Points only, no base map, so it works offline.`));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      slot.replaceChildren(alertBox('error', `Map preview unavailable: ${err.message}`));
    }
  }

  // Usage: simulations and missions that point at this dataset, plus a link to hazard analysis.
  async function renderUsage(ds, slot) {
    slot.replaceChildren(spinner('Checking what uses this dataset…'));
    const [sims, missions] = await Promise.allSettled([
      api.get('simulations', { signal }),
      api.get('missions', { signal }),
    ]);
    if (signal.aborted) return;
    const warnings = [];
    if (sims.status === 'rejected') warnings.push(`Simulation runs could not be checked: ${sims.reason && sims.reason.message}`);
    if (missions.status === 'rejected') warnings.push(`Missions could not be checked: ${missions.reason && missions.reason.message}`);
    const used = usageFor(ds.id,
      sims.status === 'fulfilled' ? listOf(sims.value) : [],
      missions.status === 'fulfilled' ? listOf(missions.value) : []);

    const rows = [
      ...used.simulations.map((s) => usageRow('Simulation', s.name || s.id,
        `${fmtDate(s.created_at)}${s.peak ? ` · peak ${s.peak.affected_rows ?? '—'} rows` : ''}`,
        `#/simulation/${encodeURIComponent(s.id)}`)),
      ...used.missions.map((m) => usageRow('Mission', m.title || m.id,
        `${m.status || ''}${m.created_at ? ` · ${fmtDate(m.created_at)}` : ''}`,
        `#/missions/${encodeURIComponent(m.id)}`)),
    ];

    const hazardLink = ds.status === 'APPROVED'
      ? h('a', { class: 'btn btn-sm', href: `#/analysis?dataset=${encodeURIComponent(ds.id)}` }, 'Run hazard analysis on this dataset')
      : h('p', { class: 'hint' }, 'Hazard analysis and simulations need an approved dataset.');

    slot.replaceChildren(
      ...warnings.map((text) => alertBox('warn', text)),
      rows.length
        ? h('ul', { class: 'ds-usage' }, rows)
        : emptyState('Not used yet', 'No simulation run or mission uses this dataset in the newest results.'),
      hazardLink);
  }

  function usageRow(kind, label, meta, href) {
    return h('li', { class: 'ds-usage-item' },
      h('span', { class: 'badge badge--neutral' }, kind),
      h('a', { href, class: 'wrap-any' }, label),
      h('span', { class: 'hint' }, meta));
  }

  refreshList();
  if (selectedId) loadDetail(selectedId);
  return () => {};
}
