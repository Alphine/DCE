// Browser-only sandbox (login demo / demo). Answers the same API paths the app calls, from a recorded bundle
// (frontend/demo/bundle.json, recorded from the local review server, usernames replaced) plus in-browser state.
// Nothing here reaches the server, and no server compute is used. Writes are kept in this browser only.
// Simplifications are labelled in the UI: new simulations and planning use a simple local model or the newest
// recorded result, and agent runs are disabled.

import { ApiError } from '../api.js';

const ON_KEY = 'dce-sandbox-on';
const STATE_KEY = 'dce-sandbox-state-v1';
const DEMO_USER = { id: 'demo-user', username: 'demo', role: 'Admin', email: null };
const CREDENTIAL = { username: 'demo', password: 'demo' };

let bundle = null;
let state = null;

export function isSandbox() {
  try { return localStorage.getItem(ON_KEY) === '1'; } catch { return false; }
}

export function isSandboxLogin(json) {
  return Boolean(json) && json.username === CREDENTIAL.username && json.password === CREDENTIAL.password;
}

export function enableSandbox() {
  try { localStorage.setItem(ON_KEY, '1'); } catch { /* private mode: the sandbox still works for this page */ }
  window.dispatchEvent(new Event('dce:sandbox-on'));
}

export function disableSandbox() {
  try { localStorage.removeItem(ON_KEY); } catch { /* ignore */ }
}

export function resetSandbox() {
  try { localStorage.removeItem(STATE_KEY); } catch { /* ignore */ }
  state = null;
}

async function loadBundle() {
  if (bundle) return bundle;
  const res = await fetch(new URL('../../demo/bundle.json', import.meta.url), { cache: 'no-store' });
  if (!res.ok) throw new ApiError(0, 'UNAVAILABLE', 'The sandbox data could not be loaded.');
  bundle = (await res.json()).keys || {};
  return bundle;
}

function rec(key) {
  return bundle && Object.prototype.hasOwnProperty.call(bundle, key) ? clone(bundle[key]) : undefined;
}

function clone(v) {
  return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
}

function loadState() {
  if (state) return state;
  try {
    const saved = JSON.parse(localStorage.getItem(STATE_KEY) || 'null');
    if (saved && saved.version === 1) { state = saved; return state; }
  } catch { /* fall through to a fresh state */ }
  const sampleWarnings = rec('GET /api/warnings') || [];
  if (!sampleWarnings.length) {
    sampleWarnings.push({
      id: 'demo-warning-en', status: 'PUBLISHED', created_at: '2026-11-08T08:00:00Z', published_at: '2026-11-08T08:05:00Z',
      decided_by: null, country_code: 'ID', lang: 'en', hazard_type: 'FLOOD', title: 'Flood warning, Jakarta (sample)',
      body: 'SAMPLE. Water levels are rising in low districts. Move to higher ground and follow official instructions.',
      content_sha256: null, created_by: null,
    });
  }
  state = {
    version: 1,
    simulationDetails: {},
    datasets: rec('GET /api/datasets') || [],
    simulations: rec('GET /api/simulations') || [],
    missions: rec('GET /api/missions') || [],
    reports: rec('GET /api/reports') || [],
    shelters: rec('GET /api/logistics/shelters') || [],
    supplies: rec('GET /api/logistics/supplies') || [],
    teams: rec('GET /api/logistics/teams') || [],
    vehicles: rec('GET /api/logistics/vehicles') || [],
    warnings: sampleWarnings,
    alerts: rec('GET /api/alerts') || [],
    tasks: rec('GET /api/agent/tasks') || [],
    users: rec('GET /api/admin/users') || [],
  };
  return state;
}

function save() {
  try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch { /* quota: keep working in memory */ }
}

function fail(status, code, message) {
  return new ApiError(status, code, message);
}

const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
const newId = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `demo-${Date.now()}-${Math.random().toString(16).slice(2)}`);
const byNewest = (a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''));

function queryString(query) {
  if (!query) return '';
  const keys = Object.keys(query).filter((k) => query[k] !== undefined && query[k] !== null && query[k] !== '').sort();
  return keys.length ? '?' + keys.map((k) => `${k}=${query[k]}`).join('&') : '';
}

// Sandbox entry point. api.js sends every request here while the sandbox is on, or for the demo login.
export async function sandboxRequest(method, path, opts = {}) {
  // Some views put the query inside the path (for example "planning/allocation?simulation_id=..."). Split it out.
  const [purePath, rawQuery] = path.split('?');
  const parts = purePath.replace(/^\/+/, '').split('/').filter(Boolean);
  const body = opts.json !== undefined ? opts.json : opts.body;
  if (method === 'POST' && purePath === 'auth/login') {
    if (isSandboxLogin(body)) { enableSandbox(); await loadBundle(); return { ok: true }; }
    throw fail(401, 'UNAUTHENTICATED', 'Use demo / demo for the sandbox, or sign in with an operator account.');
  }
  await loadBundle();
  const s = loadState();
  const query = { ...(opts.query || {}), ...Object.fromEntries(new URLSearchParams(rawQuery || '')) };
  const out = route(method, parts, query, body, opts.body, s);
  save();
  return out;
}

function route(method, parts, query, body, rawBody, s) {
  const [a, b, c] = parts;

  if (method === 'GET') {
    if (a === 'auth' && b === 'me') return clone(DEMO_USER);
    if (a === 'dashboard') return rec('GET /api/dashboard/summary') || { tasks: {}, datasets: {}, quota: {}, sandbox: {}, inference: {}, artifacts: {}, env: 'sandbox' };
    if (a === 'situation') return rec('GET /api/situation' + queryString(query)) || rec('GET /api/situation?limit=500');
    if (a === 'timeseries') return rec('GET /api/timeseries' + queryString({ hours: query.hours || 72 })) || { buckets: [], hours: 72, country: null };
    if (a === 'alerts' && !b) return filterCountry(s.alerts, query).sort(byNewest);
    if (a === 'alerts' && b === 'summary') return alertSummary(s);
    if (a === 'hazards') return hazardResult(query);
    if (a === 'public' && b === 'warnings') return publicWarnings(s, query);
    if (a === 'warnings') return filterCountry(s.warnings, query).sort(byNewest);
    if (a === 'datasets' && !b) return s.datasets.slice().sort(byNewest);
    if (a === 'datasets' && b && c === 'rows') return rec(`GET /api/datasets/${b}/rows?limit=200`) || { items: [], next_offset: null, total: 0 };
    if (a === 'datasets' && b) return findOr(s.datasets, b, 'Dataset not found.');
    if (a === 'simulations' && !b) return s.simulations.slice().sort(byNewest);
    if (a === 'simulations' && b) {
      if (s.simulationDetails && s.simulationDetails[b]) return clone(s.simulationDetails[b]);
      return findOr(s.simulations, b, 'Simulation run not found.', true);
    }
    if (a === 'planning' && b === 'allocation') return allocation(query, s);
    if (a === 'missions' && !b) return s.missions.slice().sort(byNewest);
    if (a === 'missions' && b) return missionDetail(findOr(s.missions, b, 'Mission not found.'));
    if (a === 'reports' && !b) return s.reports.slice().sort(byNewest);
    if (a === 'reports' && b) return findOr(s.reports, b, 'Report not found.');
    if (a === 'logistics' && s[b] !== undefined) return s[b].slice().sort(byNewest);
    if (a === 'agent' && b === 'tasks' && !c) return s.tasks.slice().sort(byNewest);
    if (a === 'agent' && b === 'tasks' && c) return findOr(s.tasks, c, 'Task not found.');
    if (a === 'admin' && b === 'users') return s.users.slice();
    if (a === 'admin' && b === 'api-keys') return [];
    if (a === 'sync' && b === 'snapshot') return snapshot(s);
    if (a === 'artifacts') return [];
    if (a === 'audit') return { items: [], verified: true };
  }

  if (method === 'POST') {
    if (a === 'auth' && b === 'logout') { disableSandbox(); return null; }
    if (a === 'sync' && b === 'batch') return { results: (body.items || []).map((it) => ({ op_id: it.op_id, status: 'APPLIED' })), synced_at: now() };
    if (a === 'reports' && !b) return createReport(body, s);
    if (a === 'reports' && b && c === 'review') return reviewReport(b, body, s);
    if (a === 'datasets' && !b) return uploadDataset(rawBody, s);
    if (a === 'datasets' && b && c === 'approve') return setDataset(b, 'APPROVED', s);
    if (a === 'datasets' && b && c === 'reject') return setDataset(b, 'REJECTED', s, body);
    if (a === 'hazards' || (a === 'resources' && b === 'estimate')) return resourceEstimate(body, s);
    if (a === 'simulations' && !b) return createSimulation(body, s);
    if (a === 'missions' && !b) return proposeMission(body, s);
    if (a === 'missions' && b && (c === 'approve' || c === 'reject')) return decideMission(b, c, body, s);
    if (a === 'logistics' && ['shelters', 'teams', 'vehicles'].includes(b) && !c) return addRow(b, body, s);
    if (a === 'logistics' && b === 'supplies') return upsertSupply(body, s);
    if (a === 'warnings' && !b) return createWarning(body, s);
    if (a === 'warnings' && b && c === 'publish') return setWarning(b, 'PUBLISHED', s, body);
    if (a === 'warnings' && b && c === 'withdraw') return setWarning(b, 'WITHDRAWN', s, body);
    if (a === 'alerts' && b && c === 'acknowledge') return acknowledge(b, s);
    if (a === 'agent' && b === 'tasks') throw fail(422, 'VALIDATION_FAILED', 'Agent runs are turned off in the sandbox. Open a recorded task to see its plan and output.');
    if (a === 'admin' && b === 'users' && !c) return addUser(body, s);
  }

  if (method === 'PATCH' && a === 'admin' && b === 'users' && c) return patchUser(c, body, s);
  if (method === 'PATCH' && a === 'logistics' && b && c) return patchRow(b, c, body, s);

  throw fail(404, 'NOT_FOUND', 'Not found in the sandbox.');
}

function findOr(list, id, message, fromBundle = false) {
  if (fromBundle) {
    const detail = rec(`GET /api/simulations/${id}`);
    if (detail) return detail;
  }
  const row = list.find((x) => x.id === id);
  if (row) return clone(row);
  throw fail(404, 'NOT_FOUND', message);
}

function filterCountry(list, query) {
  return list.filter((x) => !query.country || (x.country_code || 'ID') === query.country).map(clone);
}

function alertSummary(s) {
  const open = s.alerts.filter((a) => !a.acknowledged);
  const bySeverity = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  const byKind = { REPORT_VERIFIED: 0, THRESHOLD_CROSSED: 0, DECISION_WAITING: 0, SYNC_REJECTED: 0 };
  open.forEach((a) => { bySeverity[a.severity] = (bySeverity[a.severity] || 0) + 1; byKind[a.kind] = (byKind[a.kind] || 0) + 1; });
  const waiting = s.missions.filter((m) => m.status === 'PROPOSED').length + s.reports.filter((r) => r.status === 'OBSERVATION').length;
  byKind.DECISION_WAITING = waiting;
  return { total: open.length + waiting, by_severity: bySeverity, by_kind: byKind, decision_waiting: waiting, country: null };
}

function hazardResult(query) {
  const exact = rec(`GET /api/hazards${queryString(query)}`);
  if (exact) return exact;
  throw fail(422, 'VALIDATION_FAILED', 'This dataset does not have the columns this rule pack needs.');
}

function publicWarnings(s, query) {
  return s.warnings
    .filter((w) => w.status === 'PUBLISHED' && (!query.lang || w.lang === query.lang))
    .sort(byNewest)
    .map((w) => ({ id: w.id, title: w.title, body: w.body, lang: w.lang, country_code: w.country_code, hazard_type: w.hazard_type, published_at: w.published_at }));
}

function allocation(query, s) {
  const exact = rec(`GET /api/planning/allocation${queryString(query)}`);
  if (exact) return exact;
  const base = rec(`GET /api/planning/allocation?simulation_id=${(s.simulations[0] || {}).id}`) || rec(Object.keys(bundle).find((k) => k.startsWith('GET /api/planning/allocation')) || '');
  if (!base) throw fail(404, 'NOT_FOUND', 'No recorded allocation in the sandbox.');
  const run = s.simulations.find((x) => x.id === query.simulation_id);
  base.basis = { ...(base.basis || {}), simulation: { id: query.simulation_id, name: run ? run.name : 'sandbox run' }, note: 'Sandbox: the newest recorded allocation is shown for this run.' };
  return base;
}

function missionDetail(m) {
  return {
    ...m,
    objective: m.objective || '',
    area_column: m.area_column || null,
    target_areas: m.target_areas || [],
    decision: m.decision || null,
    content_sha256: m.content_sha256 || null,
    approved_content_sha256: m.approved_content_sha256 || null,
  };
}

function snapshot(s) {
  const section = (items) => ({ etag: String(items.length), count: items.length, truncated: false, items });
  return { country: null, generated_at: now(), sections: {
    reports: section(s.reports), datasets: section(s.datasets), missions: section(s.missions), simulations: section(s.simulations),
  } };
}

function createReport(body, s) {
  const row = {
    id: newId(), hazard_type: body.hazard_type, status: 'OBSERVATION', created_at: now(), observed_at: body.observed_at || null,
    reporter_role: body.reporter_role || null, severity_reported: body.severity_reported || null,
    source_reference: body.source_reference || null, notes: body.notes || null, country_code: body.country_code || null,
    location: { name: body.location_name || null, latitude: body.latitude ?? null, longitude: body.longitude ?? null },
    submitter: { id: DEMO_USER.id }, review: null, content_sha256: null,
  };
  s.reports.unshift(row);
  return clone(row);
}

function reviewReport(id, body, s) {
  const row = s.reports.find((r) => r.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Report not found.');
  if (row.status !== 'OBSERVATION') throw fail(409, 'CONFLICT', 'This report was already reviewed.');
  row.status = body.decision === 'approve' ? 'VERIFIED_OBSERVATION' : 'REJECTED';
  row.review = { at: now(), reviewer: { id: DEMO_USER.id }, decision: body.decision, note: body.note || null };
  if (row.status === 'VERIFIED_OBSERVATION') {
    s.alerts.unshift({ id: newId(), kind: 'REPORT_VERIFIED', severity: row.severity_reported || 'MEDIUM', country_code: row.country_code,
      district: null, title: `Verified ${row.hazard_type} report: ${row.location.name || 'unnamed place'}`,
      detail: { hazard_type: row.hazard_type, location_name: row.location.name, report_id: row.id },
      source: { type: 'report', id: row.id }, created_at: now(), acknowledged: false, acknowledged_by: null, acknowledged_at: null });
  }
  return clone(row);
}

async function uploadDataset(formData, s) {
  const file = formData && formData.get ? formData.get('file') : null;
  if (!file) throw fail(422, 'VALIDATION_FAILED', 'Choose a CSV file.');
  const text = await file.text();
  const lines = text.replace(/\r/g, '').split('\n').filter((l) => l.trim().length);
  const header = (lines[0] || '').split(',').map((h) => h.trim()).filter(Boolean);
  if (!header.length) throw fail(422, 'VALIDATION_FAILED', 'The file has no header row.');
  const rows = lines.slice(1).map((l) => l.split(','));
  const columns = header.map((name, i) => {
    const nulls = rows.filter((r) => !(r[i] || '').trim()).length;
    const numeric = rows.every((r) => !(r[i] || '').trim() || !Number.isNaN(Number(r[i])));
    return { name, dtype: numeric ? 'number' : 'string', nulls };
  });
  const preview = rows.slice(0, 5).map((r) => Object.fromEntries(header.map((h, i) => [h, (r[i] || '').trim() || null])));
  const row = {
    id: newId(), name: formData.get('name') || file.name, filename: file.name, kind: 'CSV', size_bytes: file.size,
    sha256: null, status: 'PENDING_VALIDATION', country_code: formData.get('country_code') || null,
    owner: { id: DEMO_USER.id }, profile: { columns, preview, rows: rows.length }, created_at: now(),
  };
  s.datasets.unshift(row);
  return clone(row);
}

function setDataset(id, status, s, body) {
  const row = s.datasets.find((d) => d.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Dataset not found.');
  row.status = status;
  row.decision = { at: now(), note: (body && body.note) || null };
  return clone(row);
}

function resourceEstimate(body, s) {
  const dsId = body && body.dataset_id;
  const exact = rec(`POST /api/resources/estimate dataset=${dsId}`);
  if (exact) return exact;
  throw fail(422, 'VALIDATION_FAILED', 'Resource estimates in the sandbox are recorded for the sample flood datasets only.');
}

function createSimulation(body, s) {
  const ds = s.datasets.find((d) => d.id === body.dataset_id);
  if (!ds) throw fail(404, 'NOT_FOUND', 'Dataset not found.');
  const sample = rec(`GET /api/datasets/${ds.id}/rows?limit=200`);
  const items = (sample && sample.items) || [];
  const mult = Number(body.depth_multiplier || 1);
  const rise = Number(body.rise_cm_per_hour || 0);
  const hours = Math.max(1, Math.min(72, Number(body.hours || 24)));
  const threshold = 50;
  const timeline = [];
  let peak = { hour: 0, affected_rows: -1 };
  for (let t = 0; t <= hours; t += 1) {
    const affected = items.filter((r) => Number(r.water_depth_cm) * mult + rise * t >= threshold).length;
    timeline.push({ hour: t, affected_rows: affected, road_blocked_candidates: affected, counts_by_severity: { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0, UNKNOWN: 0 } });
    if (affected > peak.affected_rows) peak = { hour: t, affected_rows: affected };
  }
  const districts = {};
  items.forEach((r) => {
    const d = r.district || 'unknown';
    districts[d] = districts[d] || { rows: 0, affected_rows: 0, road_blocked_candidates: 0, top_severity_rows: 0 };
    districts[d].rows += 1;
    if (Number(r.water_depth_cm) * mult + rise * peak.hour >= threshold) districts[d].affected_rows += 1;
  });
  const summary = {
    id: newId(), name: body.name || 'Sandbox run', country_code: ds.country_code || null, created_at: now(),
    created_by: { id: DEMO_USER.id }, dataset: { id: ds.id, name: ds.name }, output_sha256: null, pack_sha256: null,
    parameters: { depth_multiplier: mult, rise_cm_per_hour: rise, hours }, peak: { hour: peak.hour, affected_rows: Math.max(0, peak.affected_rows) },
  };
  const detail = { ...summary, pack: { id: 'dce-flood-illustrative', sha256: null }, dataset_sha256: null, simulator_version: 'sandbox-browser-model',
    output: { data_class: 'SIMULATED_FACT', label: 'Simulation — illustrative parameters (sandbox, simplified model)', timeline,
      peak: { hour: peak.hour, affected_rows: Math.max(0, peak.affected_rows), per_district: districts },
      model: 'Sandbox model: depth(t) = depth x multiplier + rise x t, threshold 50 cm. Not the server engine.',
      assumptions: ['Simplified browser model for the sandbox only.', 'Not for operational use.'], not_for_operational_use: true, rows_total: items.length, rows_unknown_base_depth: 0 } };
  s.simulations.unshift(summary);
  s.simulationDetails = s.simulationDetails || {};
  s.simulationDetails[summary.id] = detail;
  return clone(summary);
}

function proposeMission(body, s) {
  const row = {
    id: newId(), title: body.title, objective: body.objective, status: 'PROPOSED', created_at: now(),
    area_column: body.area_column || null, country_code: null, source: { type: body.source_type === 'REPORT' ? 'REPORT' : 'DATASET', id: body.source_id },
    target_areas: [], decision: null, proposer: { id: DEMO_USER.id }, content_sha256: null, approved_content_sha256: null,
  };
  s.missions.unshift(row);
  return clone(row);
}

function decideMission(id, action, body, s) {
  const row = s.missions.find((m) => m.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Mission not found.');
  if (row.status !== 'PROPOSED') throw fail(409, 'CONFLICT', 'This mission is not waiting for a decision.');
  row.status = action === 'approve' ? 'APPROVED' : 'REJECTED';
  row.decision = { at: now(), role: 'Approver', note: (body && body.note) || null };
  return clone(row);
}

function addRow(kind, body, s) {
  const row = { id: newId(), created_at: now(), updated_at: now(), created_by: { id: DEMO_USER.id }, ...body };
  s[kind].unshift(row);
  return clone(row);
}

function patchRow(kind, id, body, s) {
  const row = s[kind].find((x) => x.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Not found.');
  Object.assign(row, body, { updated_at: now() });
  return clone(row);
}

function upsertSupply(body, s) {
  const row = s.supplies.find((x) => x.shelter_id === body.shelter_id && x.item === body.item);
  if (row) { Object.assign(row, body, { updated_at: now() }); return clone(row); }
  const created = { id: newId(), updated_at: now(), ...body };
  s.supplies.unshift(created);
  return clone(created);
}

function createWarning(body, s) {
  const row = { id: newId(), status: 'DRAFT', created_at: now(), published_at: null, decided_by: null, country_code: body.country_code || null,
    lang: body.lang, hazard_type: body.hazard_type, title: body.title, body: body.body, content_sha256: null, created_by: { id: DEMO_USER.id } };
  s.warnings.unshift(row);
  return clone(row);
}

function setWarning(id, status, s, body) {
  const row = s.warnings.find((w) => w.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Warning not found.');
  if (status === 'PUBLISHED' && row.status !== 'DRAFT') throw fail(409, 'CONFLICT', 'Only a draft can be published.');
  row.status = status;
  row.decided_by = { id: DEMO_USER.id };
  if (status === 'PUBLISHED') row.published_at = now();
  return clone(row);
}

function acknowledge(id, s) {
  const row = s.alerts.find((a) => a.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'Alert not found.');
  row.acknowledged = true;
  row.acknowledged_by = { id: DEMO_USER.id };
  row.acknowledged_at = now();
  return clone(row);
}

function addUser(body, s) {
  const row = { id: newId(), username: body.username, role: body.role, status: 'active', email: null, created_at: now() };
  s.users.push(row);
  return clone(row);
}

function patchUser(id, body, s) {
  const row = s.users.find((u) => u.id === id);
  if (!row) throw fail(404, 'NOT_FOUND', 'User not found.');
  if (body.role) row.role = body.role;
  if (body.disabled !== undefined) row.status = body.disabled ? 'disabled' : 'active';
  if (body.email !== undefined) row.email = body.email;
  return clone(row);
}
