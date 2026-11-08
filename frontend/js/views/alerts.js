import { api } from '../api.js';
import { h, pageHead, panel, emptyState, spinner, errorState, listOf, fmtDate } from '../dom.js';
import { badge } from '../components/badges.js';
import { COUNTRIES } from '../components/countries.js';
import { timeseriesChart } from '../components/timeseries.js';
import { barRow } from '../components/mini-charts.js';
import { toast } from '../components/toast.js';
import { hasRole } from '../session.js';

const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const KIND_LABEL = {
  REPORT_VERIFIED: 'Report verified',
  THRESHOLD_CROSSED: 'Threshold crossed',
  DECISION_WAITING: 'Decision waiting',
  SYNC_REJECTED: 'Offline item rejected',
};
const SEVERITY_TONE = { CRITICAL: 'bad', HIGH: 'bad', MEDIUM: 'warn', LOW: 'neutral' };
const HOURS = [24, 72, 168];

// ctx: { user, signal }. Viewer and above can read. Reviewer and above can acknowledge.
// Alerts hold ids and counts only. This view never shows a username; the server does not send one.
export async function mount(root, ctx) {
  const { user, signal } = ctx;
  const canAck = hasRole(user, 'Reviewer');
  const state = { country: '', severity: '', openOnly: true, hours: 72 };

  const countrySelect = h('select', { id: 'al-country' },
    h('option', { value: '' }, 'All countries'),
    COUNTRIES.map((c) => h('option', { value: c.code }, `${c.name} (${c.code})`)));
  const severitySelect = h('select', { id: 'al-severity' },
    h('option', { value: '' }, 'All severities'),
    SEVERITIES.map((s) => h('option', { value: s }, s)));
  const openBox = h('input', { type: 'checkbox', id: 'al-open', checked: true });
  const hoursSelect = h('select', { id: 'al-hours' },
    HOURS.map((hr) => h('option', { value: String(hr), selected: hr === state.hours }, `Last ${hr} hours`)));

  countrySelect.addEventListener('change', () => { state.country = countrySelect.value; loadAll(); });
  severitySelect.addEventListener('change', () => { state.severity = severitySelect.value; loadList(); });
  openBox.addEventListener('change', () => { state.openOnly = openBox.checked; loadList(); });
  hoursSelect.addEventListener('change', () => { state.hours = Number(hoursSelect.value); loadSeries(); });

  const summarySlot = h('div', { 'aria-live': 'polite' }, spinner('Counting alerts…'));
  const sevSlot = h('div', { class: 'mc-sev', 'aria-live': 'polite' });
  const listSlot = h('div', { 'aria-live': 'polite' }, spinner('Loading alerts…'));
  const seriesSlot = h('div', { 'aria-live': 'polite' }, spinner('Loading reports…'));

  root.append(
    pageHead('Alerts',
      'Things that need attention: verified reports, threshold crossings, decisions waiting, and offline items the server refused. Acknowledging an alert records who did it.'),
    panel({ title: 'Needs attention', sub: 'Unacknowledged alerts for the chosen country, and decisions waiting.', style: '--i:1' }, summarySlot),
    panel({
      title: 'Alerts',
      sub: 'Newest first.',
      style: '--i:2',
      actions: [
        h('label', { class: 'small', for: 'al-country' }, 'Country'),
        countrySelect,
        h('label', { class: 'small', for: 'al-severity' }, 'Severity'),
        severitySelect,
        h('label', { class: 'small', for: 'al-open' }, openBox, ' Unacknowledged only'),
      ],
    }, sevSlot, listSlot),
    panel({
      title: 'Report intake over time',
      sub: 'Reports by hour, UTC. Viewers see verified reports only.',
      style: '--i:3',
      actions: [hoursSelect],
    }, seriesSlot),
  );

  function countryParam() {
    return state.country || undefined;
  }

  async function loadAll() {
    await Promise.all([loadSummary(), loadList(), loadSeries()]);
  }

  async function loadSummary() {
    try {
      const s = await api.get('alerts/summary', { signal, query: { country: countryParam() } });
      if (signal.aborted) return;
      summarySlot.replaceChildren(summary(s));
      sevSlot.replaceChildren(severityBars(s.by_severity || {}));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      summarySlot.replaceChildren(errorState(err, loadSummary));
      sevSlot.replaceChildren();
    }
  }

  async function loadList() {
    try {
      const rows = listOf(await api.get('alerts', {
        signal,
        query: {
          country: countryParam(),
          severity: state.severity || undefined,
          unacknowledged: state.openOnly ? true : undefined,
          limit: 200,
        },
      }));
      if (signal.aborted) return;
      listSlot.replaceChildren(rows.length
        ? table(rows)
        : emptyState('No alerts here', state.openOnly ? 'Nothing is waiting for acknowledgement.' : 'No alerts match these filters.',
          { icon: 'alerts', actions: [{ label: 'Open Situation', href: '#/situation' }] }));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, loadList));
    }
  }

  async function loadSeries() {
    try {
      const data = await api.get('timeseries', { signal, query: { country: countryParam(), hours: state.hours } });
      if (signal.aborted) return;
      seriesSlot.replaceChildren(timeseriesChart(data));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      seriesSlot.replaceChildren(errorState(err, loadSeries));
    }
  }

  function summary(s) {
    const bySeverity = s.by_severity || {};
    const byKind = s.by_kind || {};
    const waiting = s.decision_waiting || {};
    const tile = (label, value) => h('div', { class: 'alerts-tile' },
      h('span', { class: 'alerts-tile-value' }, String(value ?? 0)),
      h('span', { class: 'alerts-tile-label' }, label));
    return h('div', { class: 'alerts-summary' },
      h('div', { class: 'alerts-tiles' },
        tile('Needs attention', s.total ?? 0),
        ...SEVERITIES.map((sev) => tile(sev.toLowerCase(), bySeverity[sev] ?? 0))),
      h('ul', { class: 'alerts-kinds' },
        Object.keys(KIND_LABEL).map((kind) => h('li', null,
          h('span', null, KIND_LABEL[kind]),
          h('strong', { class: 'num' }, String(byKind[kind] ?? 0))))),
      h('p', { class: 'small muted' },
        `Waiting for a decision: ${waiting.reports_observation ?? 0} reports to review, ${waiting.missions_proposed ?? 0} missions to decide.`));
  }

  // Counts by severity as small bars above the list. Bars are scaled to the largest count.
  function severityBars(bySeverity) {
    const values = SEVERITIES.map((sev) => bySeverity[sev] ?? 0);
    const top = Math.max(0, ...values.map((v) => Number(v) || 0));
    return h('div', { class: 'mc-sev-bars', role: 'group', 'aria-label': 'Needs attention by severity' },
      h('p', { class: 'small muted' }, 'Needs attention by severity, for the chosen country'),
      SEVERITIES.map((sev, i) => barRow({
        label: sev.charAt(0) + sev.slice(1).toLowerCase(),
        value: values[i],
        max: top,
        tone: sev,
      })));
  }

  function table(rows) {
    return h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Alerts, newest first'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Time'),
          h('th', { scope: 'col' }, 'Severity'),
          h('th', { scope: 'col' }, 'Kind'),
          h('th', { scope: 'col' }, 'What'),
          h('th', { scope: 'col' }, 'Country'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Action'))),
        h('tbody', null, rows.map((a) => row(a)))));
  }

  function row(a) {
    const acknowledged = !!a.acknowledged;
    const button = canAck && !acknowledged
      ? h('button', { class: 'btn btn-sm', type: 'button', onclick: (ev) => acknowledge(a, ev.currentTarget) }, 'Acknowledge')
      : null;
    return h('tr', null,
      h('td', null, fmtDate(a.created_at)),
      h('td', null, badge(a.severity, SEVERITY_TONE[a.severity] || 'neutral')),
      h('td', null, KIND_LABEL[a.kind] || a.kind),
      h('td', { class: 'wrap-any' }, a.title),
      h('td', { class: 'mono' }, a.country_code || '—'),
      h('td', null, acknowledged ? badge('Acknowledged', 'ok') : badge('Open', 'warn')),
      h('td', null, button, !canAck && !acknowledged ? h('span', { class: 'small muted' }, 'Reviewer role needed') : null));
  }

  async function acknowledge(alert, button) {
    button.disabled = true;
    try {
      await api.postEmpty(`alerts/${encodeURIComponent(alert.id)}/acknowledge`, { signal });
      if (signal.aborted) return;
      toast('Alert acknowledged.', { kind: 'ok' });
      await loadAll();
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      toast(err.message, { kind: 'error' });
      button.disabled = false;
    }
  }

  loadAll();
  return () => {};
}

