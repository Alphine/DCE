import { h } from '../dom.js';
import { DATA_CLASS, STATE_META } from '../domain.js';

// SDD §16.3 data class badge. Focusable so keyboard users can read the tooltip.
export function dataClassBadge(cls) {
  const meta = DATA_CLASS[cls] || { tone: 'neutral', tip: `${cls}: unknown data class.` };
  return h('span', {
    class: `dc dc--${meta.tone}`,
    tabindex: '0',
    title: meta.tip,
    'data-tip': meta.tip,
    'aria-label': meta.tip,
  }, cls);
}

// Task state pill. Icon and text, so state is never conveyed by color alone.
export function stateBadge(state, { large = false } = {}) {
  const meta = STATE_META[state] || { label: state, tone: 'neutral', glyph: '?', hint: '' };
  const icon = meta.tone === 'live'
    ? h('span', { class: 'pulse', 'aria-hidden': 'true' })
    : h('span', { class: 'glyph', 'aria-hidden': 'true' }, meta.glyph);
  return h('span', {
    class: `state state--${meta.tone}${large ? ' state--lg' : ''}`,
    title: meta.hint,
  }, icon, h('span', null, meta.label));
}

export function badge(text, tone = 'neutral') {
  return h('span', { class: `badge badge--${tone}` }, text);
}

export function datasetStatusBadge(status) {
  const tone = status === 'APPROVED' ? 'ok' : status === 'REJECTED' ? 'bad' : 'warn';
  const glyph = status === 'APPROVED' ? '✓' : status === 'REJECTED' ? '✕' : '◷';
  return h('span', { class: `badge badge--${tone}` }, h('span', { 'aria-hidden': 'true' }, glyph), h('span', null, status));
}

export function chipList(items, cls = 'chip--static') {
  return h('div', { class: 'chips' }, (items || []).map((item) => h('span', { class: `chip ${cls}` }, String(item))));
}
