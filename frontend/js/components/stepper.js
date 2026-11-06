import { h } from '../dom.js';
import { BRANCH_PARENT, MAIN_FLOW, STATE_META } from '../domain.js';

// Horizontal stepper for the task state machine.
// Main flow nodes show completed / current / pending. A branch (failure or rejection)
// is drawn as a dashed crimson node after the state where it happened, and the rest of the flow is marked not reached.
export function stateStepper(state, branchParent) {
  const meta = STATE_META[state];
  const isBranch = !MAIN_FLOW.includes(state) && !!meta;
  const parent = isBranch ? (BRANCH_PARENT[state] || branchParent || 'PLANNING') : null;
  const parentIdx = isBranch ? MAIN_FLOW.indexOf(parent) : -1;
  const currentIdx = MAIN_FLOW.indexOf(state);

  const items = [];
  MAIN_FLOW.forEach((step, i) => {
    let status;
    if (isBranch) status = i <= parentIdx ? 'done' : 'skipped';
    else if (currentIdx === -1) status = 'pending';
    else if (i < currentIdx) status = 'done';
    else if (i === currentIdx) status = 'current';
    else status = 'pending';
    items.push(stepNode(step, status));
    if (isBranch && i === parentIdx) items.push(stepNode(state, 'branch'));
  });

  const label = meta ? meta.label : state;
  return h('ol', { class: 'stepper', 'aria-label': `Task state: ${label}` }, items);
}

const WORD = {
  done: 'Completed',
  current: 'Current',
  pending: 'Pending',
  skipped: 'Not reached',
  branch: 'Stopped here',
};

function stepNode(state, status) {
  const meta = STATE_META[state] || { label: state, glyph: '?', hint: '' };
  const isCurrent = status === 'current' || status === 'branch';
  const dotText = status === 'done' ? '✓' : status === 'pending' || status === 'skipped' ? '○' : meta.glyph;
  return h('li', {
    class: `step step--${status}`,
    'aria-current': isCurrent ? 'step' : undefined,
    title: meta.hint,
  },
    h('span', { class: 'step-dot', 'aria-hidden': 'true' }, dotText),
    h('span', null,
      h('span', { class: 'step-name' }, meta.label),
      h('span', { class: 'step-state' }, WORD[status])));
}
