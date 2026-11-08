// IndexedDB wrapper for offline state. Stores:
//   snapshot      keyPath "section"  read cache for list screens (reports, missions, datasets, simulations)
//   outbox        keyPath "op_id"    queued writes waiting for sync
//   session_meta  keyPath "key"      one record "current" (user id, username, role, email, last_online_check)
//                                    and one record "device" (client_id, a random UUID for this browser)
// No passwords, cookies or tokens are ever stored here. Every function rejects if IndexedDB is unavailable;
// callers decide what to do then.

const DB_NAME = 'dce-offline';
const DB_VERSION = 1;
const STORES = { snapshot: 'section', outbox: 'op_id', session_meta: 'key' };

let dbPromise = null;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      if (!('indexedDB' in globalThis)) {
        reject(new Error('IndexedDB is not available in this browser.'));
        return;
      }
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const database = req.result;
        for (const [name, keyPath] of Object.entries(STORES)) {
          if (!database.objectStoreNames.contains(name)) database.createObjectStore(name, { keyPath });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => {
        dbPromise = null;
        reject(req.error || new Error('Could not open the offline database.'));
      };
    });
  }
  return dbPromise;
}

async function run(store, mode, fn) {
  const database = await open();
  return new Promise((resolve, reject) => {
    const tx = database.transaction(store, mode);
    const request = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(request ? request.result : undefined);
    tx.onerror = () => reject(tx.error || new Error('Offline database write failed.'));
    tx.onabort = () => reject(tx.error || new Error('Offline database transaction aborted.'));
  });
}

// Generic record access. Exposed so the outbox can be built on the same store without globals.
export const store = {
  get: (name, key) => run(name, 'readonly', (s) => s.get(key)).then((v) => v ?? null),
  getAll: (name) => run(name, 'readonly', (s) => s.getAll()).then((v) => v || []),
  put: (name, value) => run(name, 'readwrite', (s) => s.put(value)),
  delete: (name, key) => run(name, 'readwrite', (s) => s.delete(key)),
  clear: (name) => run(name, 'readwrite', (s) => s.clear()),
};

export const outboxStore = {
  get: (opId) => store.get('outbox', opId),
  getAll: () => store.getAll('outbox'),
  put: (item) => store.put('outbox', item),
  delete: (opId) => store.delete('outbox', opId),
};

export const snapshotStore = {
  get: (section) => store.get('snapshot', section),
  put: (record) => store.put('snapshot', record),
  clear: () => store.clear('snapshot'),
};

export const sessionStore = {
  get: () => store.get('session_meta', 'current'),
  put: (record) => store.put('session_meta', { ...record, key: 'current' }),
  clear: () => store.delete('session_meta', 'current'),
};

export const deviceStore = {
  get: () => store.get('session_meta', 'device'),
  put: (record) => store.put('session_meta', { ...record, key: 'device' }),
};
