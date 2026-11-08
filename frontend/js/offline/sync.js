// Sync manager. Sends the outbox to POST api/sync/batch in chunks of up to 200 and applies each result.
// Runs on start, on the browser "online" event, and every 60 seconds. Refreshes the read cache from
// GET api/sync/snapshot after a run. A 401 pauses sync and keeps the outbox. A 404 means the server does not
// have the sync endpoints yet, so sync is reported as unavailable and nothing is lost.
import { api, ApiError } from '../api.js';
import { outbox } from './outbox.js';
import { snapshotStore, sessionStore, deviceStore } from './db.js';

export const BATCH_SIZE = 200;
export const SYNC_INTERVAL_MS = 60 * 1000;
export const SNAPSHOT_SECTIONS = ['reports', 'missions', 'datasets', 'simulations'];

// Splits items into batches of at most `size`. Order is kept.
export function chunk(items, size = BATCH_SIZE) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

// Maps one server result to an outbox action. APPLIED and DUPLICATE both mean the server has the item, so it
// leaves the queue. REJECTED stays queued with the reason until the user dismisses it.
export function planUpdate(result) {
  const status = result && result.status;
  if (status === 'APPLIED' || status === 'DUPLICATE') return { action: 'remove' };
  if (status === 'REJECTED') {
    const reason = (result.message && String(result.message)) || (result.code && String(result.code)) || 'Rejected by the server.';
    return { action: 'reject', last_error: reason };
  }
  return { action: 'keep' };
}

// Pairs each sent item with its result. Results are matched by op_id; if the server sent no op_id, the
// position is used. An item without a result stays pending.
export function planBatch(items, results) {
  const byId = new Map();
  (results || []).forEach((r, i) => {
    if (r && r.op_id) byId.set(r.op_id, r);
    else byId.set(`#${i}`, r);
  });
  return items.map((item, i) => {
    const result = byId.get(item.op_id) || byId.get(`#${i}`) || null;
    return { op_id: item.op_id, ...(result ? planUpdate(result) : { action: 'keep' }) };
  });
}

// Accepts a bare array or {results: []} as the batch response.
export function resultsOf(res) {
  if (Array.isArray(res)) return res;
  if (res && Array.isArray(res.results)) return res.results;
  return [];
}

// Pulls list sections out of the snapshot response. Each section may be an array or {items, etag}.
export function sectionsOf(res) {
  const root = res && res.sections && typeof res.sections === 'object' ? res.sections : res;
  const out = {};
  if (!root || typeof root !== 'object') return out;
  for (const name of SNAPSHOT_SECTIONS) {
    const entry = root[name];
    if (Array.isArray(entry)) out[name] = { items: entry, etag: null };
    else if (entry && Array.isArray(entry.items)) out[name] = { items: entry.items, etag: entry.etag || null };
  }
  return out;
}

const state = {
  started: false,
  running: false,
  paused: false,
  reachable: true,
  unavailable: false,
  lastSync: null,
  lastError: null,
  counts: { pending: 0, rejected: 0 },
};
const listeners = new Set();

export function getStatus() {
  const online = typeof navigator === 'undefined' || navigator.onLine !== false;
  return {
    online: online && state.reachable,
    pending: state.counts.pending,
    rejected: state.counts.rejected,
    paused: state.paused,
    unavailable: state.unavailable,
    running: state.running,
    lastSync: state.lastSync,
    lastError: state.lastError,
  };
}

function emit() {
  const status = getStatus();
  for (const fn of listeners) {
    try {
      fn(status);
    } catch {
      // A listener must not stop the others.
    }
  }
}

export function subscribe(fn) {
  listeners.add(fn);
  fn(getStatus());
  return () => listeners.delete(fn);
}

async function refreshCounts() {
  try {
    state.counts = await outbox.counts();
  } catch {
    // IndexedDB unavailable: keep the last known counts.
  }
}

async function clientId() {
  const existing = await deviceStore.get().catch(() => null);
  if (existing && existing.client_id) return existing.client_id;
  const client_id = globalThis.crypto.randomUUID();
  await deviceStore.put({ client_id }).catch(() => {});
  return client_id;
}

async function applyResults(batch, results) {
  const plans = planBatch(batch, results);
  for (const plan of plans) {
    const item = batch.find((x) => x.op_id === plan.op_id);
    const attempts = ((item && item.attempts) || 0) + 1;
    if (plan.action === 'remove') await outbox.remove(plan.op_id);
    else if (plan.action === 'reject') await outbox.update(plan.op_id, { status: 'rejected', last_error: plan.last_error, attempts });
    else await outbox.update(plan.op_id, { attempts });
  }
}

async function currentUserId() {
  const session = await sessionStore.get().catch(() => null);
  return session ? session.user_id : null;
}

async function refreshSnapshot() {
  const res = await api.get('sync/snapshot', { suppressAuthEvent: true });
  const userId = await currentUserId();
  const saved_at = new Date().toISOString();
  for (const [section, entry] of Object.entries(sectionsOf(res))) {
    await snapshotStore.put({ section, user_id: userId, items: entry.items, etag: entry.etag, saved_at });
  }
}

// One sync run. Safe to call at any time: it returns at once when a run is already in progress, when paused,
// or when the browser is offline.
export async function syncNow() {
  if (state.running || state.paused || (typeof navigator !== 'undefined' && navigator.onLine === false)) {
    emit();
    return;
  }
  state.running = true;
  emit();
  try {
    await refreshCounts();
    const pending = (await outbox.list()).filter((item) => item.status === 'pending');
    for (const batch of chunk(pending)) {
      const items = batch.map(({ op_id, kind, payload, made_at }) => ({ op_id, kind, payload, made_at }));
      const res = await api.post('sync/batch', { client_id: await clientId(), items }, { suppressAuthEvent: true });
      state.reachable = true;
      state.unavailable = false;
      await applyResults(batch, resultsOf(res));
    }
    try {
      await refreshSnapshot();
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 404) throw err;
    }
    state.lastSync = new Date().toISOString();
    state.lastError = null;
    const session = await sessionStore.get().catch(() => null);
    if (session) await sessionStore.put({ ...session, last_online_check: state.lastSync }).catch(() => {});
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      state.paused = true;
      state.lastError = 'Sign in again to send pending items. Nothing is lost.';
    } else if (err instanceof ApiError && err.status === 404) {
      state.unavailable = true;
      state.lastError = 'Sync is not available on this server yet. Items stay queued.';
    } else if (err instanceof ApiError && err.status === 0) {
      state.reachable = false;
      state.lastError = 'No connection. Items stay queued.';
    } else {
      state.lastError = (err && err.message) || 'Sync failed. Items stay queued.';
    }
  } finally {
    state.running = false;
    await refreshCounts();
    emit();
  }
}

// Called after a sign-in, or on boot with a live session. Remembers the user for the read cache.
// A different user than before clears the read cache, so one person never sees another's cached lists.
export async function rememberUser(user) {
  if (!user) return;
  const previous = await sessionStore.get().catch(() => null);
  if (previous && previous.user_id !== user.id) await snapshotStore.clear().catch(() => {});
  await sessionStore.put({
    user_id: user.id,
    username: user.username,
    role: user.role,
    email: user.email || null,
    last_online_check: new Date().toISOString(),
  }).catch(() => {});
  state.paused = false;
  syncNow();
}

// Called on sign-out. The read cache is removed. The outbox is kept, since those writes belong to the user.
export async function forgetUser() {
  await snapshotStore.clear().catch(() => {});
  await sessionStore.clear().catch(() => {});
  emit();
}

// The last signed-in user. Used only when the browser is offline and the server cannot confirm the session.
export async function cachedUser() {
  const s = await sessionStore.get().catch(() => null);
  if (!s) return null;
  return { id: s.user_id, username: s.username, role: s.role, email: s.email, cached: true };
}

// Answers the service worker's request for a list snapshot (see sw.js). Only the signed-in user's data is returned.
async function answerSnapshotRequest(section) {
  const session = await sessionStore.get().catch(() => null);
  const record = await snapshotStore.get(section).catch(() => null);
  if (!session || !record || record.user_id !== session.user_id) return null;
  return { items: record.items, saved_at: record.saved_at };
}

let started = false;

// Starts the timers and listeners once.
export function start() {
  if (started) return;
  started = true;
  if (typeof window === 'undefined') return;
  window.addEventListener('online', () => {
    state.reachable = true;
    syncNow();
  });
  window.addEventListener('offline', emit);
  window.addEventListener('dce:outbox', () => { refreshCounts().then(emit); });
  setInterval(() => { syncNow(); }, SYNC_INTERVAL_MS);
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type !== 'SNAPSHOT_REQUEST' || !event.ports || !event.ports[0]) return;
      answerSnapshotRequest(data.section).then((payload) => event.ports[0].postMessage(payload));
    });
  }
  refreshCounts().then(emit);
  syncNow();
}
