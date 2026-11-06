import { h } from '../dom.js';

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function clock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString(undefined, { hour12: false });
}

// Reveal text character by character in about 25 steps, so a line "types" in roughly 400 ms.
function typeOut(row, node, text) {
  if (reduceMotion.matches || !text) {
    node.textContent = text;
    return;
  }
  row.classList.add('is-typing');
  node.textContent = '';
  const step = Math.max(1, Math.ceil(text.length / 25));
  let i = 0;
  const timer = setInterval(() => {
    i = Math.min(text.length, i + step);
    node.textContent = text.slice(0, i);
    if (i >= text.length) {
      clearInterval(timer);
      row.classList.remove('is-typing');
    }
  }, 16);
}

// Live log terminal. Lines are added by append(); text is never parsed as HTML.
export function createLogTerminal({ maxLines = 1000 } = {}) {
  const status = h('span', { class: 'term-status' }, 'IDLE');
  const count = h('span', { class: 'muted small' }, '0 lines');
  const body = h('div', {
    class: 'term-body',
    role: 'log',
    'aria-live': 'off',
    'aria-label': 'Live task log',
    tabindex: '0',
  });
  const el = h('section', { class: 'panel terminal', 'aria-label': 'Live task log' },
    h('header', { class: 'term-head' },
      h('span', { class: 'term-dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')),
      h('span', { class: 'term-title' }, 'task.log'),
      count,
      status),
    body);
  let lines = 0;

  function setStatus(text, live = false) {
    status.textContent = text;
    status.className = `term-status${live ? ' is-live' : ''}`;
  }

  function addRow(stream, at, cls) {
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 48;
    const text = h('span', { class: 'term-text' });
    const row = h('div', { class: `term-line ${cls}` },
      h('span', { class: 'term-ts' }, clock(at)),
      h('span', { class: 'term-tag' }, stream),
      text);
    body.append(row);
    lines += 1;
    count.textContent = `${lines} line${lines === 1 ? '' : 's'}`;
    while (body.childElementCount > maxLines) body.firstElementChild.remove();
    if (atBottom) body.scrollTop = body.scrollHeight;
    return { row, text };
  }

  // replay: true skips the typing animation (used for catch-up replays).
  function append({ stream = 'stdout', line = '', at = null, replay = false } = {}) {
    const isErr = stream === 'stderr';
    const { row, text } = addRow(isErr ? 'ERR' : 'OUT', at, isErr ? 'stream-err' : 'stream-out');
    if (replay) text.textContent = String(line);
    else typeOut(row, text, String(line));
  }

  // System note, for example "state -> RUNNING".
  function note(message, at = new Date().toISOString()) {
    const { text } = addRow('SYS', at, 'term-line--sys');
    text.textContent = message;
  }

  function clearLines() {
    body.replaceChildren();
    lines = 0;
    count.textContent = '0 lines';
  }

  return { el, append, note, setStatus, clear: clearLines };
}
