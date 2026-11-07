import { api } from '../api.js';
import { h, fmtDate, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { hasRole } from '../session.js';

// SDD 10.7 structured intake and SDD 16.3 review. Reports carry no usernames: the server returns ids only.
export const HAZARDS = ['EARTHQUAKE', 'TSUNAMI', 'EXTREME_RAINFALL', 'FLOOD', 'LANDSLIDE', 'WILDFIRE', 'SMOKE'];
export const REPORTER_ROLES = ['CIVILIAN', 'VOLUNTEER', 'OFFICIAL', 'RESPONDER', 'OTHER'];
export const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

const STATUS_META = {
  OBSERVATION: { tone: 'warn', label: 'Awaiting review', glyph: '◷' },
  VERIFIED_OBSERVATION: { tone: 'ok', label: 'Verified', glyph: '✓' },
  REJECTED: { tone: 'bad', label: 'Rejected', glyph: '✕' },
};

export function reportStatusBadge(status) {
  const meta = STATUS_META[status] || { tone: 'neutral', label: status, glyph: '?' };
  return h('span', { class: `badge badge--${meta.tone}` }, h('span', { 'aria-hidden': 'true' }, meta.glyph), h('span', null, meta.label));
}

// Returns a client-side error message, or null when the form can be sent. The server re-checks everything.
export function validateReport(f) {
  if (!f.hazard_type) return 'Choose a hazard type.';
  const hasLat = f.latitude !== '';
  const hasLon = f.longitude !== '';
  if (hasLat !== hasLon) return 'Latitude and longitude must be given together, or both left empty.';
  if (hasLat) {
    const lat = Number(f.latitude);
    const lon = Number(f.longitude);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) return 'Latitude must be between -90 and 90.';
    if (!Number.isFinite(lon) || lon < -180 || lon > 180) return 'Longitude must be between -180 and 180.';
  }
  if (f.notes.length > 2000) return 'Notes are limited to 2000 characters.';
  return null;
}

// Builds the JSON body. Empty fields become null, and the time is sent with its UTC offset.
export function toReportBody(f) {
  const orNull = (v) => (v === '' || v === undefined ? null : v);
  let observed = null;
  if (f.observed_at) {
    const d = new Date(f.observed_at);
    if (!Number.isNaN(d.getTime())) observed = d.toISOString();
  }
  return {
    hazard_type: f.hazard_type,
    location_name: orNull(f.location_name.trim()),
    latitude: f.latitude === '' ? null : Number(f.latitude),
    longitude: f.longitude === '' ? null : Number(f.longitude),
    observed_at: observed,
    reporter_role: orNull(f.reporter_role),
    severity_reported: orNull(f.severity_reported),
    source_reference: orNull(f.source_reference.trim()),
    notes: orNull(f.notes.trim()),
  };
}

export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;
  const listSlot = h('div', null, spinner('Loading reports…'));
  const detailSlot = h('div', { class: 'stack' });

  const parts = [pageHead('Reports',
    'Field reports enter as observations. A reviewer, who is not the submitter, verifies them before viewers see them.')];
  if (hasRole(user, 'Analyst')) parts.push(intakePanel());
  parts.push(panel({ title: 'Reports', sub: hasRole(user, 'Analyst')
    ? 'All reports, newest first. Viewers see verified observations only.'
    : 'Verified observations, newest first.', style: '--i:2' }, listSlot));
  parts.push(detailSlot);
  root.append(...parts);

  async function refreshList() {
    try {
      const reports = listOf(await api.get('reports', { signal }));
      if (signal.aborted) return;
      renderList(reports);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, refreshList));
    }
  }

  function renderList(reports) {
    if (!reports.length) {
      listSlot.replaceChildren(emptyState('No reports yet',
        hasRole(user, 'Analyst') ? 'Submit a field report above.' : 'Verified observations will appear here.'));
      return;
    }
    const sorted = [...reports].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Reports'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Hazard'),
          h('th', { scope: 'col' }, 'Place'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Reported'))),
        h('tbody', null, sorted.map((r) => h('tr', { class: 'row-link' },
          h('td', null, h('a', { href: `#/reports/${encodeURIComponent(r.id)}` }, r.hazard_type)),
          h('td', { class: 'wrap-any' }, (r.location && r.location.name) || '—'),
          h('td', null, reportStatusBadge(r.status)),
          h('td', null, fmtDate(r.created_at))))))));
  }

  function intakePanel() {
    const err = h('div', { 'aria-live': 'polite' });
    const hazard = selectOf('Hazard type *', HAZARDS, { required: true, placeholder: 'Choose…' });
    const place = h('input', { id: 'rp-place', type: 'text', maxlength: '120', autocomplete: 'off' });
    const lat = h('input', { id: 'rp-lat', type: 'number', step: 'any', min: '-90', max: '90', inputmode: 'decimal' });
    const lon = h('input', { id: 'rp-lon', type: 'number', step: 'any', min: '-180', max: '180', inputmode: 'decimal' });
    const observed = h('input', { id: 'rp-observed', type: 'datetime-local' });
    const reporter = selectOf('Reporter role', REPORTER_ROLES, { placeholder: 'Not stated' });
    const severity = selectOf('Severity as reported', SEVERITIES, { placeholder: 'Not stated' });
    const source = h('input', { id: 'rp-source', type: 'text', maxlength: '120', autocomplete: 'off' });
    const notes = h('textarea', { id: 'rp-notes', rows: '3', maxlength: '2000' });
    const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Submit report');

    const form = h('form', { class: 'form-grid', novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      err.replaceChildren();
      const values = {
        hazard_type: hazard.querySelector('select').value,
        location_name: place.value,
        latitude: lat.value,
        longitude: lon.value,
        observed_at: observed.value,
        reporter_role: reporter.querySelector('select').value,
        severity_reported: severity.querySelector('select').value,
        source_reference: source.value,
        notes: notes.value,
      };
      const problem = validateReport(values);
      if (problem) { err.replaceChildren(alertBox('error', problem)); return; }
      submit.disabled = true;
      try {
        const created = await api.post('reports', toReportBody(values), { signal });
        toast('Report submitted. It waits for review.');
        form.reset();
        await refreshList();
        go(`#/reports/${encodeURIComponent(created.id)}`);
      } catch (error) {
        if (error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      } finally {
        submit.disabled = false;
      }
    } },
      hazard,
      h('div', { class: 'field' }, h('label', { for: 'rp-place' }, 'Place name'), place),
      h('div', { class: 'field' }, h('label', { for: 'rp-lat' }, 'Latitude'), lat),
      h('div', { class: 'field' }, h('label', { for: 'rp-lon' }, 'Longitude'), lon),
      h('p', { class: 'small muted field--wide' }, 'Coordinates are optional. Enter both or neither. They are never guessed from the place name.'),
      h('div', { class: 'field' }, h('label', { for: 'rp-observed' }, 'Observed at (your local time)'), observed),
      reporter,
      severity,
      h('div', { class: 'field' }, h('label', { for: 'rp-source' }, 'Source reference'), source),
      h('div', { class: 'field field--wide' }, h('label', { for: 'rp-notes' }, 'Notes (max 2000 characters)'), notes),
      err,
      h('div', { class: 'field--wide row' }, submit));
    return panel({ title: 'Submit a field report', sub: 'Structured intake (SDD 10.7). Unknown fields may stay empty.', style: '--i:1' }, form);
  }

  async function renderDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Report', style: '--i:3' }, spinner('Loading report…')));
    try {
      const r = await api.get(`reports/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      detailSlot.replaceChildren(reportDetail(r));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Report', style: '--i:3' }, errorState(err, () => renderDetail(id))));
    }
  }

  function reportDetail(r) {
    const canReview = r.status === 'OBSERVATION' && hasRole(user, 'Reviewer') && r.submitter.id !== user.id;
    const note = h('textarea', { id: 'rv-note', rows: '2', maxlength: '500', 'aria-label': 'Review note (optional)' });
    const reviewErr = h('div', { 'aria-live': 'polite' });
    const act = async (decision) => {
      reviewErr.replaceChildren();
      try {
        await api.post(`reports/${encodeURIComponent(r.id)}/review`, { decision, note: note.value.trim() || null }, { signal });
        toast(decision === 'approve' ? 'Report verified.' : 'Report rejected.');
        await refreshList();
        await renderDetail(r.id);
      } catch (error) {
        if (error.name === 'AbortError') return;
        reviewErr.replaceChildren(alertBox('error', error.message));
      }
    };
    const location = r.location || {};
    const coords = location.latitude !== null && location.latitude !== undefined
      ? `${location.latitude}, ${location.longitude}` : 'Not given';
    return panel({ title: `${r.hazard_type} report`, sub: `Status: ${r.status.replace(/_/g, ' ').toLowerCase()}`, style: '--i:3' },
      h('dl', { class: 'kv-list' },
        kv('Place', location.name || '—'),
        kv('Coordinates', coords),
        kv('Observed', fmtDate(r.observed_at)),
        kv('Reporter role', r.reporter_role || 'Not stated'),
        kv('Severity as reported', r.severity_reported || 'Not stated'),
        kv('Source reference', r.source_reference || '—'),
        kv('Submitted', fmtDate(r.created_at)),
        kv('Status', reportStatusBadge(r.status)),
        r.review ? kv('Reviewed', fmtDate(r.review.at)) : null),
      h('h3', { class: 'panel-title' }, 'Notes'),
      h('p', { class: 'pre-wrap' }, r.notes || 'No notes.'),
      canReview ? h('div', { class: 'stack' },
        h('label', { for: 'rv-note' }, 'Review note (optional)'),
        note,
        reviewErr,
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-primary', type: 'button', onclick: () => act('approve') }, 'Verify observation'),
          h('button', { class: 'btn', type: 'button', onclick: () => act('reject') }, 'Reject'))) : null,
      !canReview && r.status === 'OBSERVATION' && hasRole(user, 'Reviewer') && r.submitter.id === user.id
        ? alertBox('info', 'You submitted this report, so another reviewer must verify it.') : null);
  }

  await refreshList();
  if (selectedId) await renderDetail(selectedId);
}

// A labelled select built as a field. The label is linked to the select by id.
function selectOf(label, options, { required = false, placeholder = 'Choose…' } = {}) {
  const id = `sel-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`;
  const select = h('select', { id, required: required || undefined },
    h('option', { value: '' }, placeholder),
    options.map((o) => h('option', { value: o }, o.replace(/_/g, ' '))));
  return h('div', { class: 'field' }, h('label', { for: id }, label), select);
}
