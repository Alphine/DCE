// DOM helpers. Every piece of server data is inserted as a text node, never parsed as HTML.

import { richEmpty } from './components/empty-state.js';

export function h(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props !== null && typeof props === 'object' && !Array.isArray(props) && !(props instanceof Node)) {
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = String(value);
      else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    }
  } else if (props !== undefined && props !== null && props !== false) {
    children.unshift(props);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : dateFmt.format(d);
}

export function fmtClock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : timeFmt.format(d);
}

export function fmtBytes(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function fmtMs(ms) {
  if (ms === null || ms === undefined) return '—';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function short(text, n = 12) {
  if (text === null || text === undefined || text === '') return '—';
  const s = String(text);
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

// Accept either a bare array or a common envelope ({items: []}).
export function listOf(res) {
  if (Array.isArray(res)) return res;
  if (res && Array.isArray(res.items)) return res.items;
  return [];
}

export function pageHead(title, sub, ...actions) {
  return h('header', { class: 'page-head' },
    h('div', null,
      h('h1', { tabindex: '-1' }, title),
      sub ? h('p', null, sub) : null),
    actions.length ? h('div', { class: 'row' }, actions) : null);
}

export function panel({ title, sub, actions, cls, style, id } = {}, ...children) {
  const head = (title || actions)
    ? h('div', { class: 'panel-head' },
        h('div', null,
          title ? h('h2', { class: 'panel-title' }, title) : null,
          sub ? h('p', { class: 'panel-sub' }, sub) : null),
        actions ? h('div', { class: 'row' }, actions) : null)
    : null;
  return h('section', { class: `panel ${cls || ''}`.trim(), style, id, 'aria-label': title || undefined }, head, children);
}

export function spinner(label = 'Loading…') {
  return h('div', { class: 'state-msg', role: 'status' },
    h('span', { class: 'spinner', 'aria-hidden': 'true' }),
    h('span', null, label));
}

// options (optional): {icon, actions}. Without either, the markup is the original plain empty state.
export function emptyState(title, detail, options) {
  if (options && (options.icon || options.actions)) {
    return richEmpty({ title, detail, icon: options.icon, actions: options.actions });
  }
  return h('div', { class: 'state-msg empty' },
    h('strong', null, title),
    detail ? h('span', null, detail) : null);
}

export function alertBox(kind, text) {
  return h('div', { class: `alert alert--${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('span', { 'aria-hidden': 'true' }, kind === 'error' ? '✕' : kind === 'warn' ? '!' : 'i'),
    h('span', null, text));
}

// Error state with a retry button. Uses only the API error message.
export function errorState(err, onRetry) {
  const message = (err && err.message) || 'Something went wrong.';
  return h('div', { class: 'state-msg empty', role: 'alert' },
    h('strong', null, 'Could not load this view'),
    h('span', null, message),
    onRetry ? h('button', { class: 'btn btn-sm', type: 'button', onclick: onRetry }, 'Try again') : null);
}

export function kv(label, value) {
  return h('div', { class: 'kv' }, h('dt', null, label), h('dd', null, value ?? '—'));
}
