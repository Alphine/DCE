// Decision queue for the Command Center. Lists what is waiting for a human decision, who must decide,
// and how long it has waited. Built only from list endpoints the page already uses (docs/api.md §2):
//   missions (PROPOSED), reports (OBSERVATION), datasets (PENDING_VALIDATION), agent tasks (AWAITING_APPROVAL / AWAITING_REVIEW).
// The server enforces every rule. These checks only decide which items and controls a viewer sees.

import { h, fmtDate, short, alertBox, emptyState, panel } from '../dom.js';
import { hasRole } from '../session.js';

export const MAX_PER_TYPE = 10;
const DAY_MS = 24 * 60 * 60 * 1000;

// Order of groups on screen, with the screen each "View all" link goes to.
export const QUEUE_TYPES = [
  { type: 'mission', label: 'Missions', list: '#/missions', key: 'missions' },
  { type: 'report', label: 'Reports', list: '#/reports', key: 'reports' },
  { type: 'dataset', label: 'Datasets', list: '#/datasets', key: 'datasets' },
  { type: 'task', label: 'Agent tasks', list: '#/agent', key: 'tasks' },
];

// Agent task gates (docs/api.md §2 and gate permissions). Gate A: Approver. Gate B: Reviewer.
const TASK_GATES = {
  AWAITING_APPROVAL: { gate: 'A', decider: 'Approver', label: 'Gate A: execution plan' },
  AWAITING_REVIEW: { gate: 'B', decider: 'Reviewer', label: 'Gate B: report release' },
};

// Lowest role that may decide an item of this type. Admin passes every check through hasRole().
export function deciderFor(type, state) {
  if (type === 'mission') return 'Approver';
  if (type === 'report' || type === 'dataset') return 'Reviewer';
  if (type === 'task') return (TASK_GATES[state] || {}).decider || null;
  return null;
}

// Country as the API reports it. Rows created before country support have a null code and are shown as ID.
export function countryLabel(code) {
  return code ? String(code).toUpperCase() : 'ID';
}

// Milliseconds since an ISO timestamp, or null when the timestamp is missing or unreadable.
export function waitMs(iso, nowMs) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, nowMs - t);
}

// "under 1 min", "45 min", "3 h", "2 d". Used for the wait label on every item.
export function formatWait(ms) {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  const min = Math.floor(ms / 60000);
  if (min < 1) return 'under 1 min';
  if (min < 60) return `${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

// Oldest first. Items without a wait time sort last.
export function byOldest(a, b) {
  const aw = a.waitedMs ?? -1;
  const bw = b.waitedMs ?? -1;
  if (aw !== bw) return bw - aw;
  return String(a.id).localeCompare(String(b.id));
}

// One record as a queue item, or null when it is not waiting for a decision.
export function waitingItem(type, rec, nowMs) {
  if (!rec || rec.id === undefined || rec.id === null) return null;
  const id = String(rec.id);
  const enc = encodeURIComponent(id);
  let item = null;
  if (type === 'mission' && rec.status === 'PROPOSED') {
    item = { title: rec.title || 'Untitled mission', since: rec.created_at, ownerId: rec.proposer && rec.proposer.id,
      decider: deciderFor('mission'), href: `#/missions/${enc}`, detail: '' };
  } else if (type === 'report' && rec.status === 'OBSERVATION') {
    const place = rec.location_name ? ` · ${rec.location_name}` : '';
    item = { title: `${rec.hazard_type || 'Field'} report${place}`, since: rec.created_at, ownerId: rec.submitter && rec.submitter.id,
      decider: deciderFor('report'), href: `#/reports/${enc}`, detail: '' };
  } else if (type === 'dataset' && rec.status === 'PENDING_VALIDATION') {
    item = { title: rec.name || rec.filename || 'Untitled dataset', since: rec.created_at, ownerId: rec.owner && rec.owner.id,
      decider: deciderFor('dataset'), href: `#/datasets/${enc}`, detail: '' };
  } else if (type === 'task' && TASK_GATES[rec.state]) {
    const gate = TASK_GATES[rec.state];
    item = { title: short(rec.instruction || 'Agent task', 120), since: rec.updated_at || rec.created_at, ownerId: rec.owner && rec.owner.id,
      decider: gate.decider, href: `#/tasks/${enc}`, detail: gate.label };
  }
  if (!item) return null;
  return { type, id, ...item, country: countryLabel(rec.country_code), waitedMs: waitMs(item.since, nowMs) };
}

// Builds the queue model. `sources` holds one array per key, or null when that request failed.
// Visibility: a viewer sees items they can decide (their role passes the decider role) and items they
// proposed or submitted (marked as waiting for another person, with no decision controls).
export function buildQueue(sources, user, nowMs) {
  const groups = [];
  let oldest = null;
  for (const def of QUEUE_TYPES) {
    const records = sources[def.key];
    const failed = records === null || records === undefined;
    const all = failed ? [] : records.map((rec) => waitingItem(def.type, rec, nowMs)).filter(Boolean);
    const visible = all
      .map((it) => {
        const own = !!user && !!it.ownerId && it.ownerId === user.id;
        const canDecide = !own && !!it.decider && hasRole(user, it.decider);
        return { ...it, own, canDecide };
      })
      .filter((it) => it.own || it.canDecide)
      .sort(byOldest);
    for (const it of visible) {
      if (it.waitedMs !== null && (!oldest || it.waitedMs > oldest.waitedMs)) {
        oldest = { waitedMs: it.waitedMs, label: def.label, title: it.title };
      }
    }
    const decidable = visible.filter((it) => it.canDecide);
    const own = visible.filter((it) => it.own);
    const shown = [...decidable, ...own].slice(0, MAX_PER_TYPE);
    groups.push({
      type: def.type, label: def.label, list: def.list, failed,
      total: visible.length, decidable: decidable.length, own: own.length,
      shown, hidden: visible.length - shown.length,
    });
  }
  return { groups, oldest, failedLabels: groups.filter((g) => g.failed).map((g) => g.label) };
}

function tileNode(i, label, value, sub, cls = '') {
  return h('article', { class: `tile ${cls}`.trim(), style: `--i:${i}` },
    h('div', { class: 'tile-label' }, label),
    h('div', { class: 'tile-value' }, value),
    h('div', { class: 'tile-sub' }, sub));
}

function itemRow(it) {
  const waited = formatWait(it.waitedMs);
  const meta = [
    h('span', null, `Country ${it.country}`),
    it.detail ? h('span', null, it.detail) : null,
    h('time', { datetime: it.since || '', title: fmtDate(it.since) }, `waited ${waited}`),
    h('span', null, it.own ? `Waiting for ${it.decider}` : `${it.decider} to decide`),
  ];
  let action;
  if (it.own) {
    action = h('span', { class: 'badge badge--neutral' }, 'Waiting for another person');
  } else if (it.canDecide) {
    action = h('a', { class: 'btn btn-sm', href: it.href }, 'Open to decide');
  } else {
    action = h('span', { class: 'small muted' }, `${it.decider} decides`);
  }
  return h('li', { class: `dq-item${it.own ? ' dq-item--own' : ''}` },
    h('div', { class: 'dq-main' },
      h('span', { class: 'dq-title' }, it.title),
      h('span', { class: 'dq-meta' }, meta)),
    action);
}

function groupNode(g) {
  const rows = [];
  const firstOwn = g.shown.findIndex((it) => it.own);
  g.shown.forEach((it, index) => {
    if (index === firstOwn && g.decidable > 0) rows.push(h('li', { class: 'dq-sub', role: 'presentation' }, 'Your submissions'));
    rows.push(itemRow(it));
  });
  return h('section', { class: 'dq-group', 'aria-label': g.label },
    h('div', { class: 'dq-group-head' },
      h('h3', { class: 'dq-group-title' }, g.label),
      h('span', { class: 'small muted' }, `${g.total} waiting`),
      h('a', { class: 'small', href: g.list }, 'View all')),
    g.failed ? alertBox('warn', `Could not load ${g.label.toLowerCase()}. The other items are shown. Use Refresh to try again.`) : null,
    rows.length ? h('ul', { class: 'dq-list', 'aria-label': `${g.label} waiting for a decision` }, rows) : null,
    g.hidden > 0 ? h('p', { class: 'small muted' }, `${g.hidden} more. `, h('a', { href: g.list }, `View all ${g.label.toLowerCase()}`)) : null);
}

// Panel with KPI tiles, one group per type, and a notice for each request that failed.
// `model` comes from buildQueue(). Waits are measured at load time, so they are as of the last refresh.
export function decisionQueuePanel(model) {
  const { groups, oldest, failedLabels } = model;
  const countTile = (i, g) => {
    const label = `${g.label} waiting`;
    if (g.failed) return tileNode(i, label, '—', 'Could not load');
    const parts = [g.decidable ? `${g.decidable} to decide` : null, g.own ? `${g.own} yours` : null].filter(Boolean);
    return tileNode(i, label, String(g.total), parts.join(' · ') || 'None waiting');
  };
  const tiles = [
    ...groups.map((g, i) => countTile(i, g)),
    tileNode(groups.length, 'Oldest wait',
      oldest ? formatWait(oldest.waitedMs) : '—',
      oldest ? `${oldest.label}: ${short(oldest.title, 40)}` : 'Nothing waiting',
      oldest && oldest.waitedMs > DAY_MS ? 'tile--bad' : (oldest ? 'tile--amber' : '')),
  ];

  const visibleTotal = groups.reduce((acc, g) => acc + g.total, 0);
  let body;
  if (visibleTotal === 0 && !failedLabels.length) {
    body = emptyState('Nothing is waiting for a decision.');
  } else if (visibleTotal === 0) {
    body = h('p', { class: 'small muted' }, 'No waiting items could be checked. See the notices above for the parts that did not load.');
  } else {
    body = groups.filter((g) => g.total > 0 || g.failed).map(groupNode);
  }
  if (visibleTotal === 0 && failedLabels.length) {
    body = [...groups.filter((g) => g.failed).map(groupNode), body];
  }

  return panel({
    title: 'Decision queue',
    sub: 'What needs a decision now, oldest first. Waits are as of the last refresh. Items you proposed or submitted show as waiting for another person.',
    cls: 'panel--queue',
  },
    h('div', { class: 'indicators dq-tiles' }, tiles),
    body);
}
