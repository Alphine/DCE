// Read cache for list screens. A successful list load is saved to the snapshot store. When the network
// fails, the last saved list for the signed-in user is returned with the time it was saved.
// The service worker can also answer with a snapshot ({from_snapshot: true, items, saved_at}); both paths
// are handled here.
import { api } from '../api.js';
import { listOf, fmtDate, alertBox } from '../dom.js';
import { snapshotStore, sessionStore } from './db.js';
import { isNetworkError } from './outbox.js';

// Returns { items, savedAt }. savedAt is null when the list came from the server.
export async function loadList(section, path, { signal } = {}) {
  const session = await sessionStore.get().catch(() => null);
  const userId = session ? session.user_id : null;
  try {
    const res = await api.get(path, { signal });
    if (res && res.from_snapshot) return { items: listOf(res), savedAt: res.saved_at || null };
    const items = listOf(res);
    snapshotStore.put({ section, user_id: userId, items, etag: null, saved_at: new Date().toISOString() }).catch(() => {});
    return { items, savedAt: null };
  } catch (err) {
    if (!isNetworkError(err)) throw err;
    const cached = await snapshotStore.get(section).catch(() => null);
    if (cached && userId && cached.user_id === userId) return { items: cached.items, savedAt: cached.saved_at };
    throw err;
  }
}

// The notice shown above a list that came from saved data.
export function cacheNotice(savedAt) {
  return alertBox('info', `Showing saved data from ${fmtDate(savedAt)}. You are offline or the server is unreachable.`);
}
