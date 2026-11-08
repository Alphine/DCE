// Fetch wrapper for the DCE API (docs/api.md). Relative URLs only ("api/..."),
// so the app works at "/" and under a sub-path. Every non-2xx response is mapped
// to ApiError using the contract's error shape. Stack traces are never shown.

export class ApiError extends Error {
  constructor(status, code, message, requestId = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

const FALLBACK_MESSAGES = {
  UNAUTHENTICATED: 'Please sign in to continue.',
  FORBIDDEN: 'Your role cannot do this.',
  SELF_APPROVAL_NOT_ALLOWED: 'You cannot approve your own submission. Another reviewer must do it.',
  QUOTA_EXCEEDED: 'Daily agent task quota reached.',
  RATE_LIMITED: 'Too many requests. Wait a moment and try again.',
  VALIDATION_FAILED: 'Some input is invalid.',
  NOT_FOUND: 'Not found.',
  CONFLICT: 'This conflicts with the current state. Refresh and try again.',
  INVALID_STATE: 'This action is not valid for the current task state.',
  UNAVAILABLE: 'The service is unavailable right now. Check your connection and try again.',
  INTERNAL: 'Something went wrong on the server.',
};

const authListeners = new Set();
// Called when any request returns UNAUTHENTICATED (session expired or missing).
export function onUnauthenticated(fn) {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

function apiUrl(path, query) {
  const url = new URL(`api/${String(path).replace(/^\/+/, '')}`, document.baseURI);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
  }
  return url;
}

function codeForStatus(status) {
  if (status === 401) return 'UNAUTHENTICATED';
  if (status === 403) return 'FORBIDDEN';
  if (status === 404) return 'NOT_FOUND';
  if (status === 409) return 'CONFLICT';
  if (status === 429) return 'RATE_LIMITED';
  if (status >= 500) return 'INTERNAL';
  return 'VALIDATION_FAILED';
}

async function toApiError(res) {
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    // Not JSON: fall back to status-based messages.
  }
  const err = payload && typeof payload === 'object' ? payload.error : null;
  const code = (err && err.code) || codeForStatus(res.status);
  const message = (err && typeof err.message === 'string' && err.message) || FALLBACK_MESSAGES[code] || `Request failed (HTTP ${res.status}).`;
  return new ApiError(res.status, code, message, (err && err.request_id) || null);
}

async function request(method, path, opts = {}) {
  const { json, body, query, signal, raw = false, suppressAuthEvent = false } = opts;
  const headers = { Accept: raw ? '*/*' : 'application/json' };
  const init = { method, credentials: 'same-origin', headers, signal, cache: 'no-store' };
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  } else if (body !== undefined) {
    init.body = body; // FormData: the browser sets the multipart boundary
  }

  let res;
  try {
    res = await fetch(apiUrl(path, query), init);
  } catch (err) {
    if (err && err.name === 'AbortError') throw err;
    throw new ApiError(0, 'UNAVAILABLE', FALLBACK_MESSAGES.UNAVAILABLE);
  }

  if (!res.ok) {
    const error = await toApiError(res);
    if (error.code === 'UNAUTHENTICATED' && !suppressAuthEvent) {
      authListeners.forEach((fn) => fn(error));
    }
    throw error;
  }
  if (raw) return res;
  if (res.status === 204) return null;
  const type = res.headers.get('content-type') || '';
  return type.includes('application/json') ? res.json() : res.text();
}

export const api = {
  get: (path, opts) => request('GET', path, opts),
  post: (path, json, opts = {}) => request('POST', path, { ...opts, json }),
  patch: (path, json, opts = {}) => request('PATCH', path, { ...opts, json }),
  postEmpty: (path, opts) => request('POST', path, opts),
  upload: (path, formData, opts) => request('POST', path, { ...opts, body: formData }),
  // Binary download with the server's SHA-256 header (X-Content-SHA256).
  async blob(path, opts) {
    const res = await request('GET', path, { ...opts, raw: true });
    return {
      blob: await res.blob(),
      sha256: res.headers.get('X-Content-SHA256'),
      contentType: res.headers.get('content-type') || '',
    };
  },
};
