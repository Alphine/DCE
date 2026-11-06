import { api } from '../api.js';
import { h, listOf, pageHead, panel, emptyState, spinner, alertBox, short, fmtDate } from '../dom.js';
import { stateBadge, dataClassBadge } from '../components/badges.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';

const EXAMPLES = [
  'Analyze this flood incident dataset. Identify affected areas, detect blocked roads, estimate resource requirements, and generate a situation report.',
  'Profile the dataset, count the districts where water depth exceeds 30 cm, and draft a short situation report for the operations room.',
  'Plot water depth by district and list the three districts with the highest average depth.',
];

const OUTPUTS = [
  { id: 'affected_areas', label: 'Affected areas' },
  { id: 'blocked_roads', label: 'Blocked roads' },
  { id: 'resource_requirements', label: 'Resource requirements' },
  { id: 'situation_report', label: 'Situation report' },
];
const DEFAULT_OUTPUTS = new Set(['affected_areas', 'blocked_roads', 'situation_report']);

// ctx: { signal, navigate }. Analyst role or higher (guarded by app.js).
export async function mount(root, ctx) {
  const { signal } = ctx;
  const outputs = new Set(DEFAULT_OUTPUTS);

  const instruction = h('textarea', {
    id: 'agent-instruction',
    rows: '6',
    maxlength: '4000',
    placeholder: 'Describe the analysis you need. Name the outputs you expect.',
    'aria-describedby': 'agent-instruction-hint',
  });
  const counter = h('span', { id: 'agent-instruction-hint', class: 'hint' }, '0 / 4000');
  instruction.addEventListener('input', () => { counter.textContent = `${instruction.value.length} / 4000`; });

  const formError = h('div', { 'aria-live': 'polite' });
  const dsSelect = h('select', { id: 'agent-dataset', required: true });
  const dsNote = h('div');
  const quotaSlot = h('div', null, spinner('Loading quota…'));
  const recentSlot = h('div', null, spinner('Loading tasks…'));
  const submit = h('button', { class: 'btn btn-primary btn-gate', type: 'submit' }, 'Plan this analysis');

  const exampleChips = EXAMPLES.map((text, i) => h('button', {
    class: 'chip', type: 'button', 'aria-label': `Use example prompt ${i + 1}`,
    onclick: () => {
      instruction.value = text;
      counter.textContent = `${text.length} / 4000`;
      instruction.focus();
    },
  }, `Example ${i + 1}`));

  const outputChips = OUTPUTS.map((o) => {
    const chip = h('button', { class: 'chip', type: 'button', 'aria-pressed': outputs.has(o.id) ? 'true' : 'false' }, o.label);
    chip.addEventListener('click', () => {
      const on = !outputs.has(o.id);
      if (on) outputs.add(o.id); else outputs.delete(o.id);
      chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    return chip;
  });

  const form = h('form', { novalidate: true, onsubmit: onSubmit, 'aria-label': 'Create agent task' },
    h('div', { class: 'field' },
      h('label', { class: 'label', for: 'agent-instruction' }, 'Instruction'),
      instruction,
      h('div', { class: 'row', style: 'justify-content:space-between' },
        h('div', { class: 'chips', role: 'group', 'aria-label': 'Example prompts' }, exampleChips),
        counter)),
    h('div', { class: 'field' },
      h('label', { class: 'label', for: 'agent-dataset' }, 'Approved dataset'),
      dsSelect,
      dsNote),
    h('div', { class: 'field' },
      h('span', { class: 'label', id: 'outputs-label' }, 'Requested outputs'),
      h('div', { class: 'chips', role: 'group', 'aria-labelledby': 'outputs-label' }, outputChips)),
    formError,
    h('div', { class: 'row' }, submit,
      h('span', { class: 'hint' }, 'Gate A follows: a human approves the plan and limits before any code runs.')));

  async function onSubmit(event) {
    event.preventDefault();
    formError.replaceChildren();
    const text = instruction.value.trim();
    if (!text) return showError('Write an instruction for the agent.');
    if (!dsSelect.value) return showError('Choose an approved dataset.');
    if (!outputs.size) return showError('Pick at least one requested output.');

    submit.disabled = true;
    submit.textContent = 'Submitting…';
    try {
      const task = await api.post('agent/tasks', {
        instruction: text,
        dataset_id: dsSelect.value,
        requested_outputs: [...outputs],
      }, { signal });
      if (signal.aborted) return;
      toast('Task created. The planner is drafting a plan.', { kind: 'success' });
      go(`#/tasks/${encodeURIComponent(task.id)}`);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      showError(err.message);
      toast(err.message, { kind: 'error' });
      loadQuota();
    } finally {
      if (!signal.aborted) {
        submit.disabled = false;
        submit.textContent = 'Plan this analysis';
      }
    }
  }

  function showError(message) {
    formError.replaceChildren(alertBox('error', message));
  }

  async function loadDatasets() {
    try {
      const datasets = listOf(await api.get('datasets', { signal })).filter((d) => d.status === 'APPROVED');
      if (signal.aborted) return;
      dsSelect.replaceChildren(
        h('option', { value: '' }, datasets.length ? 'Select an approved dataset' : 'No approved datasets'),
        ...datasets.map((d) => h('option', { value: d.id }, `${d.name || d.filename} (${short(d.id, 8)})`)));
      if (!datasets.length) {
        dsNote.replaceChildren(alertBox('warn', 'No approved datasets. Upload a CSV on the Datasets screen and ask a reviewer to approve it.'),
          h('a', { href: '#/datasets', class: 'small' }, 'Go to Datasets'));
        submit.disabled = true;
      } else {
        dsNote.replaceChildren(h('p', { class: 'hint' }, 'Only approved datasets are listed. Approval is required before the agent can read data.'));
      }
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      dsNote.replaceChildren(alertBox('error', err.message));
    }
  }

  async function loadQuota() {
    try {
      const s = await api.get('dashboard/summary', { signal });
      if (signal.aborted) return;
      const used = (s.quota && s.quota.used_today) || 0;
      const limit = (s.quota && s.quota.limit) || 0;
      const remaining = Math.max(0, limit - used);
      const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
      quotaSlot.replaceChildren(
        h('div', { class: 'tile-value', style: 'font-size:2.2rem' }, `${remaining}`),
        h('p', { class: 'tile-sub' }, `remaining of ${limit || '—'} agent tasks today (${used} used)`),
        h('div', { class: 'meter', role: 'meter', 'aria-label': 'Daily agent task quota used', 'aria-valuemin': '0', 'aria-valuemax': String(limit || 0), 'aria-valuenow': String(used) },
          h('span', { style: `width:${pct}%` })),
        h('p', { class: 'hint', style: 'margin-top:12px' }, `Sandbox runner: ${(s.sandbox && s.sandbox.runner) || 'unknown'}. Inference: ${(s.inference && s.inference.mode) || 'unknown'}.`));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      quotaSlot.replaceChildren(alertBox('error', err.message));
    }
  }

  async function loadRecent() {
    try {
      const tasks = listOf(await api.get('agent/tasks', { signal }))
        .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
        .slice(0, 5);
      if (signal.aborted) return;
      if (!tasks.length) return recentSlot.replaceChildren(emptyState('No tasks yet', 'Your first plan will appear here.'));
      recentSlot.replaceChildren(h('div', null, tasks.map((t) => h('a', { class: 'feed-row', href: `#/tasks/${encodeURIComponent(t.id)}` },
        h('span', { class: 'feed-title' }, short(t.instruction, 90)),
        stateBadge(t.state),
        h('span', { class: 'feed-meta' }, h('span', { class: 'mono' }, short(t.id, 8)), h('span', null, fmtDate(t.created_at)))))));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      recentSlot.replaceChildren(alertBox('error', err.message));
    }
  }

  const flow = h('ol', { class: 'flow', 'aria-label': 'How an agent task moves through the system' },
    ['Instruction', 'Plan', 'Gate A: approve plan', 'Sandbox run', 'Gate B: release'].map((label, i) =>
      h('li', { class: 'flow-step', style: `--i:${i}` }, h('span', { class: 'flow-n', 'aria-hidden': 'true' }, String(i + 1)), h('span', null, label))));

  root.append(
    pageHead('Disaster Commander Agent',
      'Describe the analysis. The planner drafts a plan, a human approves the plan and limits, and code then runs in an isolated sandbox.'),
    flow,
    h('div', { class: 'grid-2', style: 'grid-template-columns:minmax(0,1.6fr) minmax(280px,1fr)' },
      panel({ title: 'Mission brief', sub: 'Outputs are SIMULATED_FACT until a reviewer releases them at gate B.', style: '--i:1' },
        h('div', { class: 'row', style: 'margin-bottom:14px' }, dataClassBadge('SIMULATED_FACT')),
        form),
      h('div', { class: 'stack' },
        panel({ title: 'Quota', style: '--i:2' }, quotaSlot),
        panel({ title: 'Your recent tasks', style: '--i:3' }, recentSlot))));

  loadDatasets();
  loadQuota();
  loadRecent();
  return () => {};
}
