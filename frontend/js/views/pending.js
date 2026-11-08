import { h, fmtDate, pageHead, panel, emptyState, alertBox } from '../dom.js';
import { toast } from '../components/toast.js';
import { list, dismiss, KIND_LABELS } from '../offline/outbox.js';
import { subscribe, syncNow } from '../offline/sync.js';

// Pending panel: every queued write, its status, and any rejection reason. Only rejected items can be dismissed.
// A decision made offline is not effective until the server accepts it.

const STATUS_TEXT = {
  pending: 'Waiting to send',
  rejected: 'Rejected by the server',
};

export async function mount(root, ctx) {
  const { signal } = ctx;
  const listSlot = h('div', { class: 'stack', 'aria-live': 'polite' });
  const syncLine = h('p', { class: 'small muted' });

  const syncNowBtn = h('button', { class: 'btn btn-sm', type: 'button', onclick: async () => {
    syncNowBtn.disabled = true;
    await syncNow();
    syncNowBtn.disabled = false;
    toast('Sync finished. Check the list for any changes.');
  } }, 'Sync now');

  root.append(pageHead('Pending',
    'Writes made offline wait here until the server accepts them. Decisions are not effective until accepted.'),
  panel({ title: 'Queued on this device', sub: 'Oldest first. Rejected items stay until you dismiss them.', style: '--i:1',
    actions: [syncNowBtn] },
  syncLine, listSlot));

  let items = [];

  async function render(status) {
    syncLine.textContent = status.paused
      ? 'Sync is paused. Sign in again to send these items.'
      : status.unavailable
        ? 'The server does not offer sync yet. Items stay queued.'
        : status.online
          ? (status.lastSync ? `Last sync ${fmtDate(status.lastSync)}.` : 'Not synced yet in this session.')
          : 'You are offline. Items will be sent when you are back online.';
    try {
      items = await list();
    } catch (err) {
      listSlot.replaceChildren(alertBox('error', err.message));
      return;
    }
    if (!items.length) {
      listSlot.replaceChildren(emptyState('Nothing waiting', 'Writes made offline will appear here until they are sent.'));
      return;
    }
    listSlot.replaceChildren(...items.map(renderItem));
  }

  function renderItem(item) {
    const rejected = item.status === 'rejected';
    const onDismiss = async () => {
      try {
        const removed = await dismiss(item.op_id);
        if (removed) toast('Rejected item dismissed.');
      } catch (err) {
        toast(err.message, { kind: 'error' });
      }
    };
    return h('article', { class: `pending-item ${rejected ? 'pending-item--rejected' : ''}`.trim(), 'aria-label': KIND_LABELS[item.kind] || item.kind },
      h('div', { class: 'pending-item-head' },
        h('strong', null, KIND_LABELS[item.kind] || item.kind),
        h('span', { class: `badge badge--${rejected ? 'bad' : 'warn'}` }, STATUS_TEXT[item.status] || item.status)),
      h('p', { class: 'small muted' }, `Made ${fmtDate(item.made_at)} · ${item.attempts || 0} send attempt${item.attempts === 1 ? '' : 's'}`),
      rejected && item.last_error ? alertBox('error', item.last_error) : null,
      rejected ? h('div', { class: 'row' },
        h('button', { class: 'btn btn-sm', type: 'button', onclick: onDismiss }, 'Dismiss')) : null);
  }

  const unsubscribe = subscribe((status) => { render(status); });
  signal.addEventListener('abort', () => unsubscribe());
  return () => unsubscribe();
}
