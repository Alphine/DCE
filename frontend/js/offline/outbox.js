// Outbox: queued writes. An item is removed when the server applies or de-duplicates it, and kept with a
// reason when the server rejects it. Rejected items leave only when the user dismisses them.
import { outboxStore } from './db.js';
import { ApiError } from '../api.js';

export const KINDS = ['REPORT_CREATE', 'REPORT_DECISION', 'MISSION_PROPOSE', 'MISSION_DECISION', 'SIMULATION_CREATE'];
export const KIND_LABELS = {
  REPORT_CREATE: 'Field report',
  REPORT_DECISION: 'Report verify or reject',
  MISSION_PROPOSE: 'Mission proposal',
  MISSION_DECISION: 'Mission approve or reject',
  SIMULATION_CREATE: 'Scenario run',
};
export const SAVED_OFFLINE_MESSAGE = 'Saved offline. It will be sent when you are back online.';

// A transport failure: fetch threw (api.js uses status 0), or the service worker reported the API as unavailable.
export function isNetworkError(err) {
  return err instanceof ApiError && (err.status === 0 || err.code === 'UNAVAILABLE');
}

// Tells the rest of the app that the queue changed. Sync and the header listen for this event.
function announce() {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event('dce:outbox'));
  }
}

// Pure factory so the logic can be tested with an in-memory store. The app uses the instance below.
export function createOutbox(store, { randomUUID = () => globalThis.crypto.randomUUID(), now = () => new Date().toISOString(), onChange = announce } = {}) {
  async function enqueue(kind, payload) {
    if (!KINDS.includes(kind)) throw new Error(`Unknown outbox kind: ${kind}`);
    const item = {
      op_id: randomUUID(),
      kind,
      payload,
      made_at: now(),
      status: 'pending',
      last_error: null,
      attempts: 0,
    };
    await store.put(item);
    onChange();
    return item.op_id;
  }

  async function list() {
    const items = await store.getAll();
    return items.sort((a, b) => String(a.made_at).localeCompare(String(b.made_at)));
  }

  async function counts() {
    const items = await store.getAll();
    let pending = 0;
    let rejected = 0;
    for (const item of items) {
      if (item.status === 'rejected') rejected += 1;
      else pending += 1;
    }
    return { pending, rejected };
  }

  async function update(opId, patch) {
    const current = await store.get(opId);
    if (!current) return null;
    const next = { ...current, ...patch };
    await store.put(next);
    onChange();
    return next;
  }

  async function remove(opId) {
    await store.delete(opId);
    onChange();
  }

  // Only rejected items can be dismissed. Pending items always wait for the server.
  async function dismiss(opId) {
    const current = await store.get(opId);
    if (!current || current.status !== 'rejected') return false;
    await store.delete(opId);
    onChange();
    return true;
  }

  return { enqueue, list, counts, update, remove, dismiss };
}

export const outbox = createOutbox(outboxStore);

export const enqueue = outbox.enqueue;
export const list = outbox.list;
export const counts = outbox.counts;
export const dismiss = outbox.dismiss;

// Runs a write online, or queues it when offline or when the request never reaches the server.
// Returns { queued: false, result } or { queued: true, op_id }. Other errors are rethrown unchanged.
export function createSubmit(queue, isOnline = () => typeof navigator === 'undefined' || navigator.onLine !== false) {
  return async function submitOrQueue(kind, payload, send) {
    if (!isOnline()) return { queued: true, op_id: await queue.enqueue(kind, payload) };
    try {
      return { queued: false, result: await send() };
    } catch (err) {
      if (isNetworkError(err)) return { queued: true, op_id: await queue.enqueue(kind, payload) };
      throw err;
    }
  };
}

export const submitOrQueue = createSubmit(outbox);
