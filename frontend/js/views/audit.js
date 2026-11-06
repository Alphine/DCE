import { api } from '../api.js';
import { h, pageHead, panel, emptyState, spinner, alertBox, short, fmtDate, errorState } from '../dom.js';
import { copyButton } from '../components/copy.js';
import { toast } from '../components/toast.js';
import { can } from '../session.js';

const PAGE = 25;

// ctx: { user, signal }. Reviewer and above can read. Admin can verify the hash chain.
export async function mount(root, ctx) {
  const { user, signal } = ctx;
  let offset = 0;
  let lastCount = 0;
  let verifySlot = null;

  const tableSlot = h('div', null, spinner('Loading audit records…'));
  const prev = h('button', { class: 'btn btn-sm', type: 'button', onclick: () => { offset = Math.max(0, offset - PAGE); load(); } }, 'Previous');
  const next = h('button', { class: 'btn btn-sm', type: 'button', onclick: () => { offset += PAGE; load(); } }, 'Next');
  const pager = h('div', { class: 'pager' }, h('span', { class: 'small muted', 'aria-live': 'polite' }, ''), prev, next);

  const parts = [
    pageHead('Decision Audit',
      'Append-only, hash-chained record of state changes, approvals and sandbox events. It stores IDs and hashes, never secrets, raw data or full prompts.'),
  ];

  if (can.verifyAudit(user)) {
    verifySlot = h('div', { 'aria-live': 'polite' });
    const verifyBtn = h('button', { class: 'btn btn-primary btn-sm', type: 'button' }, 'Verify chain');
    verifyBtn.addEventListener('click', async () => {
      verifyBtn.disabled = true;
      verifySlot.replaceChildren(spinner('Recomputing the hash chain…'));
      try {
        const res = await api.postEmpty('audit/verify', { signal });
        if (signal.aborted) return;
        verifySlot.replaceChildren(verdict(res));
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        verifySlot.replaceChildren(alertBox('error', err.message));
        toast(err.message, { kind: 'error' });
      } finally {
        if (!signal.aborted) verifyBtn.disabled = false;
      }
    });
    parts.push(panel({
      title: 'Chain verification',
      sub: 'Recomputes every row_hash from prev_hash. Admin only.',
      actions: [verifyBtn],
      style: '--i:1',
    }, verifySlot));
  } else {
    parts.push(panel({ title: 'Chain verification', style: '--i:1' },
      alertBox('info', `Chain verification is an Admin action. Your role (${user.role}) can read records but not verify the chain.`)));
  }

  parts.push(panel({ title: 'Audit records', sub: `Newest first. Page size ${PAGE}.`, style: '--i:2' }, tableSlot, pager));
  root.append(...parts);

  // Accepts { valid } or { ok } or { status }. Unknown shapes are shown as unknown, not as valid.
  function verdict(res) {
    const data = res && typeof res === 'object' ? res : {};
    let state = 'unknown';
    if (typeof data.valid === 'boolean') state = data.valid ? 'ok' : 'bad';
    else if (typeof data.ok === 'boolean') state = data.ok ? 'ok' : 'bad';
    else if (typeof data.status === 'string') state = /valid|ok|pass/i.test(data.status) && !/invalid/i.test(data.status) ? 'ok' : /invalid|fail|broken|tamper/i.test(data.status) ? 'bad' : 'unknown';

    const headline = state === 'ok' ? 'Chain valid' : state === 'bad' ? 'Chain invalid' : 'Result unclear';
    const glyph = state === 'ok' ? '✓' : state === 'bad' ? '✕' : '?';
    const detail = [];
    if (data.checked !== undefined) detail.push(`Checked ${data.checked} records.`);
    if (data.broken_at !== undefined && data.broken_at !== null) detail.push(`First broken record: ${data.broken_at}.`);
    if (data.message) detail.push(String(data.message));
    detail.push(`Verified at ${fmtDate(new Date().toISOString())}.`);
    return h('div', { class: `verdict verdict--${state}`, role: 'status' },
      h('span', { class: 'verdict-glyph', 'aria-hidden': 'true' }, glyph),
      h('div', null,
        h('strong', null, headline),
        h('span', { class: 'small' }, detail.join(' '))),
      h('details', { style: 'margin-left:auto' },
        h('summary', null, 'raw response'),
        h('pre', { class: 'json-cell' }, JSON.stringify(res, null, 2))));
  }

  async function load() {
    prev.disabled = offset === 0;
    try {
      const res = await api.get('audit', { signal, query: { limit: PAGE, offset } });
      if (signal.aborted) return;
      const records = Array.isArray(res) ? res : (res && res.items) || [];
      lastCount = records.length;
      next.disabled = lastCount < PAGE;
      pager.firstElementChild.textContent = records.length
        ? `Records ${offset + 1}–${offset + records.length}`
        : 'No records on this page';
      tableSlot.replaceChildren(records.length ? table(records) : emptyState('No audit records', 'Records appear as tasks and approvals happen.'));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      tableSlot.replaceChildren(errorState(err, load));
    }
  }

  function table(records) {
    return h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Audit records'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col', class: 'num' }, '#'),
          h('th', { scope: 'col' }, 'Time'),
          h('th', { scope: 'col' }, 'Actor'),
          h('th', { scope: 'col' }, 'Action'),
          h('th', { scope: 'col' }, 'Subject'),
          h('th', { scope: 'col' }, 'Detail'),
          h('th', { scope: 'col' }, 'Row hash'))),
        h('tbody', null, records.map((r) => h('tr', null,
          h('td', { class: 'num mono' }, String(r.id)),
          h('td', null, fmtDate(r.at)),
          h('td', null, r.actor || '—'),
          h('td', { class: 'mono' }, r.action),
          h('td', { class: 'mono' }, short(r.subject, 12)),
          h('td', null, h('pre', { class: 'json-cell' }, JSON.stringify(r.detail ?? {}))),
          h('td', null,
            h('div', { class: 'hash-row' },
              h('span', { class: 'hash', title: r.row_hash || '' }, short(r.row_hash, 12)),
              r.row_hash ? copyButton(r.row_hash, `Copy row hash of record ${r.id}`) : null)))))));
  }

  load();
  return () => {};
}
