import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv, short } from '../dom.js';
import { chipList } from '../components/badges.js';
import { toast } from '../components/toast.js';
import { go, parseHash } from '../router.js';
import { hasRole } from '../session.js';
import { loadList, cacheNotice } from '../offline/read-cache.js';
import { submitOrQueue, SAVED_OFFLINE_MESSAGE } from '../offline/outbox.js';
import { countryField, countryOrNull } from '../components/countries.js';

// SDD 15.2 to 15.4. A mission is proposed by an Analyst from approved data, then an Approver who did not
// propose it approves or rejects it. Approval never starts a sandbox run. "Executed" is not recorded here.
// On open the newest mission is shown. The proposal form sits below the list and opens when there are no
// missions, or when it arrives from Planning with a simulation run name (?run=...&simulation=...).

const STATUS_META = {
  PROPOSED: { tone: 'warn', label: 'Proposed', glyph: '◷' },
  APPROVED: { tone: 'ok', label: 'Approved', glyph: '✓' },
  REJECTED: { tone: 'bad', label: 'Rejected', glyph: '✕' },
};

// Status chip: glyph and text, so state is never carried by colour alone. Styled in runs.css.
export function missionStatusBadge(status) {
  const meta = STATUS_META[status] || { tone: 'neutral', label: String(status), glyph: '?' };
  return h('span', { class: `status-chip status-chip--${meta.tone}` },
    h('span', { class: 'status-chip-glyph', 'aria-hidden': 'true' }, meta.glyph),
    h('span', null, meta.label));
}

const UNITS = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
const rtf = typeof Intl !== 'undefined' && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }) : null;

// Age of a proposal, such as "3 hours ago". Returns '' for a missing or invalid date.
export function ageLabel(iso, now = Date.now()) {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const diff = Math.round((t - now) / 1000);
  for (const [unit, secs] of UNITS) {
    if (Math.abs(diff) >= secs) {
      const n = Math.round(diff / secs);
      return rtf ? rtf.format(n, unit) : `${Math.abs(n)} ${unit}${Math.abs(n) === 1 ? '' : 's'} ago`;
    }
  }
  return 'just now';
}

// Newest first by created_at (ISO strings sort as text). Returns a new array.
export function newestMissions(missions) {
  return listOf(missions).slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
}

// Client-side checks only. The server re-checks source status, column, and length.
export function validateProposal(f) {
  if (!f.title.trim()) return 'Give the mission a title.';
  if (!f.objective.trim()) return 'Describe the objective.';
  if (f.source_type === 'DATASET') {
    if (!f.source_id) return 'Choose an approved dataset.';
    if (!f.area_column) return 'Choose the column that names the target areas.';
  } else if (!f.source_id) {
    return 'Choose a verified report.';
  }
  return null;
}

// Prefill from Planning. The run name is a plain value and goes into input values, never into HTML.
export function prefillFromQuery(query) {
  const run = query && query.get('run') ? query.get('run').trim() : '';
  if (!run) return null;
  return {
    title: `Response to ${run}`.slice(0, 120),
    objective: `Prioritise the districts in the simulation "${run}" at its peak hour. Illustrative until approved.`.slice(0, 1000),
    runName: run,
  };
}

export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;
  const canPropose = hasRole(user, 'Analyst');
  const prefill = canPropose ? prefillFromQuery(parseHash().query) : null;
  const detailSlot = h('div', { class: 'stack' });
  const listSlot = h('div', null, spinner('Loading missions…'));

  root.append(pageHead('Missions',
    'Proposed missions wait for a human approver. Approval records who decided and the hash of the content approved.'));
  root.append(detailSlot);
  root.append(panel({ title: 'Missions', sub: canPropose
    ? 'Newest first. Viewers see approved missions only.'
    : 'Approved missions, newest first.', style: '--i:2' }, listSlot));
  const proposeBox = canPropose ? proposePanel() : null;
  if (proposeBox) root.append(proposeBox);

  let missions = [];

  async function refreshList() {
    try {
      const { items, savedAt } = await loadList('missions', 'missions', { signal });
      if (signal.aborted) return null;
      missions = newestMissions(items);
      renderList(missions);
      if (savedAt) listSlot.prepend(cacheNotice(savedAt));
      return missions;
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return null;
      listSlot.replaceChildren(errorState(err, () => refreshList().then(openTarget)));
      return null;
    }
  }

  function renderList(missions) {
    if (!missions.length) {
      listSlot.replaceChildren(canPropose
        ? emptyState('No missions yet',
          'Propose one from an approved dataset or a verified report in the form below. It waits for an approver.',
          { icon: 'missions', actions: [{ label: 'Open Datasets', href: '#/datasets' }, { label: 'Open Reports', href: '#/reports' }] })
        : emptyState('No approved missions yet',
          'Missions appear here once an approver has approved them.',
          { icon: 'missions', actions: [{ label: 'Open Planning', href: '#/planning' }] }));
      if (proposeBox) proposeBox.open = true;
      return;
    }
    const activeId = selectedId || missions[0].id;
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Missions, newest first'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Title'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Proposed by'),
          h('th', { scope: 'col' }, 'Source'),
          h('th', { scope: 'col', class: 'num' }, 'Target areas'),
          h('th', { scope: 'col' }, 'Proposed'))),
        h('tbody', null, missions.map((m) => h('tr', { class: m.id === activeId ? 'row-link is-selected' : 'row-link' },
          h('td', { class: 'wrap-any' }, h('a', { href: `#/missions/${encodeURIComponent(m.id)}` }, m.title)),
          h('td', null, missionStatusBadge(m.status)),
          h('td', { class: 'wrap-any' }, (m.proposer && m.proposer.username) || '—'),
          h('td', null, m.source.type === 'DATASET' ? 'Dataset' : 'Verified report'),
          h('td', { class: 'num' }, String((m.target_areas || []).length)),
          h('td', null,
            h('time', { datetime: m.created_at, title: fmtDate(m.created_at) }, ageLabel(m.created_at) || fmtDate(m.created_at)))))))));
  }

  // The proposal form loads the approved CSV datasets and verified reports the caller may use.
  function proposePanel() {
    const err = h('div', { 'aria-live': 'polite' });
    const sourceType = h('select', { id: 'ms-type' },
      h('option', { value: 'DATASET' }, 'Approved CSV dataset'),
      h('option', { value: 'REPORT' }, 'Verified report'));
    const sourceSel = h('select', { id: 'ms-source', required: true });
    const column = h('select', { id: 'ms-column' });
    const title = h('input', { id: 'ms-title', type: 'text', maxlength: '120', required: true });
    const objective = h('textarea', { id: 'ms-objective', rows: '3', maxlength: '1000', required: true });
    if (prefill) {
      title.value = prefill.title;
      objective.value = prefill.objective;
    }
    const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Propose mission');
    const country = countryField('ms-country');
    const columnField = h('div', { class: 'field', id: 'ms-column-field' }, h('label', { for: 'ms-column' }, 'Target-area column'), column);
    const hint = h('p', { class: 'small muted' }, 'Target areas are the distinct values of the column you choose. You do not type them in.');
    const sourceField = h('div', { class: 'field' }, h('label', { for: 'ms-source' }, 'Source'), sourceSel);

    let datasets = [];
    let reports = [];

    async function loadSources() {
      try {
        const [ds, rp] = await Promise.all([api.get('datasets', { signal }), api.get('reports', { signal })]);
        if (signal.aborted) return;
        datasets = listOf(ds).filter((d) => d.status === 'APPROVED' && d.kind === 'CSV');
        reports = listOf(rp).filter((r) => r.status === 'VERIFIED_OBSERVATION' && r.location && r.location.name);
        refillSources();
      } catch (error) {
        if (signal.aborted || error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      }
    }

    function refillSources() {
      const isDataset = sourceType.value === 'DATASET';
      columnField.hidden = !isDataset;
      hint.hidden = !isDataset;
      const items = isDataset ? datasets : reports;
      const label = (x) => (isDataset ? (x.name || x.filename) : `${x.hazard_type} · ${x.location.name}`);
      sourceSel.replaceChildren(
        h('option', { value: '' }, items.length ? 'Choose…' : 'Nothing available yet'),
        ...items.map((x) => h('option', { value: x.id }, label(x))));
      column.replaceChildren();
    }

    async function loadColumns() {
      column.replaceChildren(h('option', { value: '' }, 'Loading…'));
      const ds = datasets.find((d) => d.id === sourceSel.value);
      const cols = ds && ds.profile && Array.isArray(ds.profile.columns) ? ds.profile.columns : [];
      column.replaceChildren(h('option', { value: '' }, cols.length ? 'Choose a column' : 'No columns'),
        ...cols.map((c) => h('option', { value: c.name }, c.name)));
    }

    sourceType.addEventListener('change', refillSources);
    sourceSel.addEventListener('change', () => { if (sourceType.value === 'DATASET') loadColumns(); });

    const form = h('form', { class: 'form-grid', novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      err.replaceChildren();
      const values = {
        source_type: sourceType.value,
        source_id: sourceSel.value,
        area_column: sourceType.value === 'DATASET' ? column.value : '',
        title: title.value,
        objective: objective.value,
      };
      const problem = validateProposal(values);
      if (problem) { err.replaceChildren(alertBox('error', problem)); return; }
      const body = { source_type: values.source_type, source_id: values.source_id, title: values.title.trim(),
        objective: values.objective.trim(), area_column: values.source_type === 'DATASET' ? values.area_column : null,
        country_code: countryOrNull(country.select.value) };
      submit.disabled = true;
      try {
        const out = await submitOrQueue('MISSION_PROPOSE', body, () => api.post('missions', body, { signal }));
        form.reset();
        refillSources();
        if (out.queued) {
          toast(SAVED_OFFLINE_MESSAGE);
          await refreshList();
          return;
        }
        toast('Mission proposed. It waits for an approver.');
        await refreshList();
        go(`#/missions/${encodeURIComponent(out.result.id)}`);
      } catch (error) {
        if (error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      } finally {
        submit.disabled = false;
      }
    } },
      prefill ? alertBox('info', `Started from simulation run "${prefill.runName}". Pick the approved dataset and its district column, then propose.`) : null,
      h('div', { class: 'field' }, h('label', { for: 'ms-type' }, 'Source type'), sourceType),
      sourceField,
      country.field,
      columnField,
      hint,
      h('div', { class: 'field' }, h('label', { for: 'ms-title' }, 'Title'), title),
      h('div', { class: 'field field--wide' }, h('label', { for: 'ms-objective' }, 'Objective'), objective),
      err,
      h('div', { class: 'field--wide row' }, submit));
    loadSources();
    return h('details', { class: 'run-new', id: 'ms-new', open: !!prefill },
      h('summary', null, 'Propose a mission'),
      h('p', { class: 'small muted' }, 'Analyst role. Approval is a separate step for an Approver.'),
      form);
  }

  async function renderDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Mission', style: '--i:1' }, spinner('Loading mission…')));
    try {
      const m = await api.get(`missions/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      detailSlot.replaceChildren(missionDetail(m));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Mission', style: '--i:1' }, errorState(err, () => renderDetail(id))));
    }
  }

  // Opens the URL's mission, or the newest one when the URL names none.
  async function openTarget() {
    if (selectedId) return renderDetail(selectedId);
    if (missions.length) return renderDetail(missions[0].id);
    detailSlot.replaceChildren();
    return undefined;
  }

  function missionDetail(m) {
    const isApprover = hasRole(user, 'Approver');
    const isOwn = m.proposer && m.proposer.id === user.id;
    const canDecide = m.status === 'PROPOSED' && isApprover && !isOwn;
    const note = h('textarea', { id: 'md-note', rows: '2', maxlength: '500', 'aria-label': 'Decision note (optional)' });
    const decideErr = h('div', { 'aria-live': 'polite' });
    const approveBtn = h('button', { class: 'btn btn-primary', type: 'button', onclick: () => decide('approve') }, 'Approve mission');
    const rejectBtn = h('button', { class: 'btn', type: 'button', onclick: () => decide('reject') }, 'Reject');
    const decide = async (action) => {
      decideErr.replaceChildren();
      const noteText = note.value.trim() || null;
      try {
        const out = await submitOrQueue('MISSION_DECISION',
          { mission_id: m.id, decision: action, content_sha256: m.content_sha256 || null, note: noteText },
          () => api.post(`missions/${encodeURIComponent(m.id)}/${action}`, { note: noteText }, { signal }));
        if (out.queued) {
          // A pending decision is not effective until the server accepts it. Keep the buttons off until it is sent.
          approveBtn.disabled = true;
          rejectBtn.disabled = true;
          toast(SAVED_OFFLINE_MESSAGE);
          decideErr.replaceChildren(alertBox('info', 'Your decision is saved on this device. It takes effect only when the server accepts it.'));
          await refreshList();
          return;
        }
        toast(action === 'approve' ? 'Mission approved.' : 'Mission rejected.');
        await refreshList();
        await renderDetail(m.id);
      } catch (error) {
        if (error.name === 'AbortError') return;
        decideErr.replaceChildren(alertBox('error', error.message));
      }
    };

    const sourceLabel = m.source.type === 'DATASET' ? 'Approved CSV dataset' : 'Verified report';
    const proposerName = (m.proposer && m.proposer.username) || 'unknown';
    const decidedBy = m.decision && m.decision.decided_by ? m.decision.decided_by.username : 'an approver';
    const targets = Array.isArray(m.target_areas) ? m.target_areas : [];

    const history = h('ol', { class: 'timeline-list', 'aria-label': 'Decision history' },
      h('li', { class: 'tl-item tl-item--done' },
        h('strong', null, 'Proposed'),
        h('span', null, ` by ${proposerName} · ${fmtDate(m.created_at)}`)),
      m.decision
        ? h('li', { class: `tl-item tl-item--${m.status === 'APPROVED' ? 'ok' : 'bad'}` },
          h('strong', null, m.status === 'APPROVED' ? 'Approved' : 'Rejected'),
          h('span', null, ` by ${decidedBy} (${m.decision.role}) · ${fmtDate(m.decision.at)}`),
          m.decision.note ? h('p', { class: 'tl-note' }, `Note: ${m.decision.note}`) : null)
        : h('li', { class: 'tl-item tl-item--wait' },
          h('strong', null, 'Waiting for an approver'),
          h('span', null, ' No decision yet.')));

    let roleNote = null;
    if (m.status === 'PROPOSED') {
      if (isOwn) roleNote = alertBox('info', 'You proposed this mission, so another approver must decide it.');
      else if (!isApprover) roleNote = alertBox('info', 'Only an Approver or Admin can approve or reject this mission.');
    }

    return panel({ title: m.title, actions: [missionStatusBadge(m.status)], style: '--i:1' },
      h('h3', { class: 'panel-title' }, 'Objective'),
      h('p', { class: 'mission-objective' }, m.objective),
      h('dl', { class: 'kv-list' },
        kv('Source', `${sourceLabel} · ${short(m.source.id, 8)}`),
        kv('Target-area column', m.area_column || '—'),
        kv('Proposed by', proposerName),
        kv('Proposed', `${fmtDate(m.created_at)}${ageLabel(m.created_at) ? ` (${ageLabel(m.created_at)})` : ''}`),
        kv('Content hash', short(m.content_sha256, 16)),
        m.approved_content_sha256 ? kv('Approved hash', short(m.approved_content_sha256, 16)) : null),
      h('h3', { class: 'panel-title' }, `Target areas (${targets.length})`),
      targets.length ? chipList(targets) : h('p', { class: 'muted' }, 'None.'),
      h('h3', { class: 'panel-title' }, 'Decision history'),
      history,
      roleNote,
      canDecide ? h('div', { class: 'stack decide-box' },
        h('label', { for: 'md-note' }, 'Decision note (optional)'),
        note,
        decideErr,
        h('div', { class: 'row' }, approveBtn, rejectBtn)) : null);
  }

  const loaded = await refreshList();
  if (loaded !== null) {
    await openTarget();
  } else if (selectedId) {
    await renderDetail(selectedId);
  }
}
