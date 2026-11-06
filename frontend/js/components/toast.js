import { h } from '../dom.js';

let host = null;

function getHost() {
  if (!host) {
    host = document.getElementById('toasts');
    if (!host) {
      host = h('div', { id: 'toasts', class: 'toasts', 'aria-live': 'polite' });
      document.body.append(host);
    }
  }
  return host;
}

// kind: info | success | error. Errors stay longer and use role="alert".
export function toast(message, { kind = 'info', timeout } = {}) {
  const text = typeof message === 'string' ? message : (message && message.message) || 'Something went wrong.';
  const glyph = kind === 'error' ? '✕' : kind === 'success' ? '✓' : 'i';
  let timer = null;
  const node = h('div', { class: `toast toast--${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('span', { class: 'toast-glyph', 'aria-hidden': 'true' }, glyph),
    h('span', { class: 'toast-text' }, text),
    h('button', { class: 'toast-close', type: 'button', 'aria-label': 'Dismiss notification', onclick: () => remove() }, '×'));

  function remove() {
    clearTimeout(timer);
    node.classList.add('leaving');
    setTimeout(() => node.remove(), 220);
  }

  const container = getHost();
  container.append(node);
  while (container.children.length > 4) container.firstElementChild.remove();
  timer = setTimeout(remove, timeout ?? (kind === 'error' ? 8000 : 4500));
  return remove;
}
