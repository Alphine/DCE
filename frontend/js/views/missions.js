import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv, short } from '../dom.js';
import { chipList } from '../components/badges.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { hasRole } from '../session.js';

// SDD 15.2 to 15.4. A mission is proposed by an Analyst from approved data, then an Approver who did not
// propose it approves or rejects it. Approval never starts a sandbox run. "Executed" is not recorded here.

const STATUS_META = {
  PROPOSED: { tone: 'warn', label: 'Proposed', glyph: '◷' },
  APPROVED: { tone: 'ok', label: 'Approved', glyph: '✓' },
  REJECTED: { tone: 'bad', label: 'Rejected', glyph: '✕' },
};

export function missionStatusBadge(status) {
  const meta = STATUS_META[status] || { tone: 'neutral', label: status, glyph: '?' };
  return h('span', { class: `badge badge--${meta.tone}` }, h('span', { 'aria-hidden': 'true' }, meta.glyph), h('span', null, meta.label));
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

export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;
  const listSlot = h('div', null, spinner('Loading missions…'));
  const detailSlot = h('div', { class: 'stack' });

  const parts = [pageHead('Missions',
    'Proposed missions wait for a human approver. Approval records who decided and the hash of the content approved.')];
  if (hasRole(user, 'Analyst')) parts.push(proposePanel());
  parts.push(panel({ title: 'Missions', sub: hasRole(user, 'Analyst')
    ? 'Newest first. Viewers see approved missions only.'
    : 'Approved missions, newest first.', style: '--i:2' }, listSlot));
  parts.push(detailSlot);
  root.append(...parts);

  async function refreshList() {
    try {
      const missions = listOf(await api.get('missions', { signal }));
      if (signal.aborted) return;
      renderList(missions);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, refreshList));
    }
  }

  function renderList(missions) {
    if (!missions.length) {
      listSlot.replaceChildren(emptyState('No missions yet',
        hasRole(user, 'Analyst') ? 'Propose one from an approved dataset or a verified report above.' : 'Approved missions will appear here.'));
      return;
    }
    const sorted = [...missions].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Missions'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Title'),
          h('th', { scope: 'col' }, 'Source'),
          h('th', { scope: 'col', class: 'num' }, 'Target areas'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Proposed'))),
        h('tbody', null, sorted.map((m) => h('tr', { class: 'row-link' },
          h('td', { class: 'wrap-any' }, h('a', { href: `#/missions/${encodeURIComponent(m.id)}` }, m.title)),
          h('td', null, m.source.type === 'DATASET' ? 'Dataset' : 'Verified report'),
          h('td', { class: 'num' }, String(m.target_areas.length)),
          h('td', null, missionStatusBadge(m.status)),
          h('td', null, fmtDate(m.created_at))))))));
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
    const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Propose mission');
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
        items.map((x) => h('option', { value: x.id }, label(x))));
      column.replaceChildren();
    }

    async function loadColumns() {
      column.replaceChildren(h('option', { value: '' }, 'Loading…'));
      const ds = datasets.find((d) => d.id === sourceSel.value);
      const cols = ds && ds.profile && Array.isArray(ds.profile.columns) ? ds.profile.columns : [];
      column.replaceChildren(h('option', { value: '' }, cols.length ? 'Choose a column' : 'No columns'),
        cols.map((c) => h('option', { value: c.name }, c.name)));
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
        objective: values.objective.trim(), area_column: values.source_type === 'DATASET' ? values.area_column : null };
      submit.disabled = true;
      try {
        const created = await api.post('missions', { json: body, signal });
        toast('Mission proposed. It waits for an approver.');
        form.reset();
        refillSources();
        await refreshList();
        go(`#/missions/${encodeURIComponent(created.id)}`);
      } catch (error) {
        if (error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      } finally {
        submit.disabled = false;
      }
    } },
      h('div', { class: 'field' }, h('label', { for: 'ms-type' }, 'Source type'), sourceType),
      sourceField,
      columnField,
      hint,
      h('div', { class: 'field' }, h('label', { for: 'ms-title' }, 'Title'), title),
      h('div', { class: 'field field--wide' }, h('label', { for: 'ms-objective' }, 'Objective'), objective),
      err,
      h('div', { class: 'field--wide row' }, submit));
    loadSources();
    return panel({ title: 'Propose a mission', sub: 'Analyst role. Approval is a separate step for an Approver.', style: '--i:1' }, form);
  }

  async function renderDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Mission', style: '--i:3' }, spinner('Loading mission…')));
    try {
      const m = await api.get(`missions/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      detailSlot.replaceChildren(missionDetail(m));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Mission', style: '--i:3' }, errorState(err, () => renderDetail(id))));
    }
  }

  function missionDetail(m) {
    const canDecide = m.status === 'PROPOSED' && hasRole(user, 'Approver') && m.proposer.id !== user.id;
    const note = h('textarea', { id: 'md-note', rows: '2', maxlength: '500', 'aria-label': 'Decision note (optional)' });
    const decideErr = h('div', { 'aria-live': 'polite' });
    const decide = async (action) => {
      decideErr.replaceChildren();
      try {
        await api.post(`missions/${encodeURIComponent(m.id)}/${action}`, { json: { note: note.value.trim() || null }, signal });
        toast(action === 'approve' ? 'Mission approved.' : 'Mission rejected.');
        await refreshList();
        await renderDetail(m.id);
      } catch (error) {
        if (error.name === 'AbortError') return;
        decideErr.replaceChildren(alertBox('error', error.message));
      }
    };
    const sourceLabel = m.source.type === 'DATASET' ? 'Approved CSV dataset' : 'Verified report';
    return panel({ title: m.title, sub: `Status: ${m.status.toLowerCase()}`, style: '--i:3' },
      h('dl', { class: 'kv-list' },
        kv('Objective', m.objective),
        kv('Source', sourceLabel),
        kv('Target-area column', m.area_column || '—'),
        kv('Status', missionStatusBadge(m.status)),
        kv('Proposed', fmtDate(m.created_at)),
        kv('Content hash', short(m.content_sha256, 16)),
        m.approved_content_sha256 ? kv('Approved hash', short(m.approved_content_sha256, 16)) : null),
      h('h3', { class: 'panel-title' }, 'Target areas'),
      m.target_areas.length ? chipList(m.target_areas) : h('p', { class: 'muted' }, 'None.'),
      m.decision ? alertBox(m.status === 'APPROVED' ? 'info' : 'warn',
        `${m.status === 'APPROVED' ? 'Approved' : 'Rejected'} by a ${m.decision.role} on ${fmtDate(m.decision.at)}.${m.decision.note ? ` Note: ${m.decision.note}` : ''}`) : null,
      canDecide ? h('div', { class: 'stack' },
        h('label', { for: 'md-note' }, 'Decision note (optional)'),
        note,
        decideErr,
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-primary', type: 'button', onclick: () => decide('approve') }, 'Approve mission'),
          h('button', { class: 'btn', type: 'button', onclick: () => decide('reject') }, 'Reject'))) : null,
      m.status === 'PROPOSED' && hasRole(user, 'Approver') && m.proposer.id === user.id
        ? alertBox('info', 'You proposed this mission, so another approver must decide it.') : null,
      m.status === 'PROPOSED' && !hasRole(user, 'Approver')
        ? alertBox('info', 'Only an approver can approve or reject this mission.') : null);
  }

  await refreshList();
  if (selectedId) await renderDetail(selectedId);
}
