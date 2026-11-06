import { h } from '../dom.js';

// Web Crypto is only available in a secure context (https or localhost).
export const canHash = !!(globalThis.crypto && globalThis.crypto.subtle);

export async function sha256Hex(buffer) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

// Returns { status: 'verified' | 'mismatch' | 'unavailable', actual }.
export async function verifyBlob(blob, expectedHex) {
  if (!canHash) return { status: 'unavailable', actual: null };
  const actual = await sha256Hex(await blob.arrayBuffer());
  const ok = !!expectedHex && actual === String(expectedHex).toLowerCase();
  return { status: ok ? 'verified' : 'mismatch', actual };
}

const VERIFY_COPY = {
  verified: { cls: 'verify-status--ok', glyph: '✓', text: 'Hash verified in your browser' },
  mismatch: { cls: 'verify-status--bad', glyph: '✕', text: 'Hash mismatch. Do not trust this file' },
  unavailable: { cls: 'verify-status--warn', glyph: '!', text: 'Not verified: needs HTTPS or localhost' },
};

export function hashStatus(result) {
  const copy = VERIFY_COPY[result.status] || VERIFY_COPY.unavailable;
  return h('span', { class: `verify-status ${copy.cls}`, role: 'status' },
    h('span', { 'aria-hidden': 'true' }, copy.glyph),
    h('span', null, copy.text));
}
