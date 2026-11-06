import { api } from '../api.js';
import { h, clear, listOf, pageHead, emptyState, spinner, errorState, alertBox, short, fmtDate, fmtMs, fmtBytes, kv } from '../dom.js';
import { stateBadge, dataClassBadge, badge, chipList } from '../components/badges.js';
import { stateStepper } from '../components/stepper.js';
import { createLogTerminal } from '../components/log-terminal.js';
import { copyButton } from '../components/copy.js';
import { verifyBlob, hashStatus } from '../components/hash.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { can, isOwner } from '../session.js';
import { TERMINAL_STATES, STATE_META, derivedBranchParent } from '../domain.js';

const RECONNECT_MAX_MS = 30000;
const enc = encodeURIComponent;

const VALIDATION_TEXT = {
  PLANNING: 'No outputs yet.',
  AWAITING_APPROVAL: 'No outputs yet. Code has not been generated.',
  QUEUED: 'No outputs yet. The sandbox has not started.',
  RUNNING: 'The sandbox is running. Outputs appear after the run.',
  OUTPUT_VALIDATING: 'Validating output files. Types, sizes and hashes are checked.',
  REJECTED_OUTPUT: 'Output validation failed. Files were not released.',
  AWAITING_REVIEW: 'Validated. Waiting for gate B before results are visible.',
  COMPLETED: 'Released after gate B.',
};

// ctx: { user, params, signal }
export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const id = params.id;

  const term = createLogTerminal();
  const memo = new Map();
  const blobUrls = [];
  let task = null;
  let artifacts = [];
  let es = null;
  let reconnectTimer = null;
  let refreshTimer = null;
  let retries = 0;
  let ended = false;
  let paused = false;
  let cancelArmed = false;
  let cancelTimer = null;

  const headSlot = h('header', { class: 'task-head', 'aria-live': 'polite' }, spinner('Loading task…'));
  const slots = {};
  const makeSlot = (name) => {
    const el = h('section', { class: 'panel', 'data-slot': name });
    slots[name] = el;
    return el;
  };
  const stepperEl = makeSlot('stepper');
  const planEl = makeSlot('plan');
  const gateAEl = makeSlot('gateA');
  const codeEl = makeSlot('code');
  const sandboxEl = makeSlot('sandbox');
  const artifactEl = makeSlot('artifacts');
  const gateBEl = makeSlot('gateB');

  root.append(
    headSlot,
    h('div', { class: 'task-grid' },
      h('div', { class: 'task-main' }, stepperEl, planEl, gateAEl, codeEl, sandboxEl, artifactEl, gateBEl),
      h('aside', { class: 'task-side' }, term.el)));

  // Paint a slot only when its inputs change, so typed notes and open panels survive live updates.
  function paint(name, key, build) {
    const el = slots[name];
    if (!el || memo.get(name) === key) return;
    memo.set(name, key);
    el.replaceChildren(...build().filter(Boolean));
  }

  const panelHead = (title, sub, extra) => h('div', { class: 'panel-head' },
    h('div', null,
      h('h2', { class: 'panel-title' }, title),
      sub ? h('p', { class: 'panel-sub' }, sub) : null),
    extra ? h('div', { class: 'row' }, extra) : null);

  function fail(err) {
    if (signal.aborted || (err && err.name === 'AbortError')) return;
    toast(err.message, { kind: 'error' });
  }

  // ---------- Data loading ----------
  async function fetchAll() {
    const t = await api.get(`agent/tasks/${enc(id)}`, { signal });
    let list;
    try {
      list = listOf(await api.get(`agent/tasks/${enc(id)}/artifacts`, { signal }));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') throw err;
      list = Array.isArray(t.artifacts) ? t.artifacts : [];
    }
    if (signal.aborted) return;
    task = t;
    artifacts = list;
    paintAll();
  }

  // One fetch at a time. A request that arrives mid-fetch triggers one more pass, so no update is lost.
  let refreshing = false;
  let refreshAgain = false;
  async function runRefresh() {
    if (refreshing) {
      refreshAgain = true;
      return;
    }
    refreshing = true;
    try {
      do {
        refreshAgain = false;
        await fetchAll();
      } while (refreshAgain && !signal.aborted);
    } catch (err) {
      if (!signal.aborted && err.name !== 'AbortError') {
        headSlot.replaceChildren(errorState(err, () => go(`#/tasks/${enc(id)}`)));
      }
    } finally {
      refreshing = false;
    }
  }
  function scheduleRefresh(delay = 250) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(runRefresh, delay);
  }

  // ---------- Painting ----------
  function paintAll() {
    paintHeader();
    paintStepper();
    paintPlan();
    paintGateA();
    paintCode();
    paintSandbox();
    paintArtifacts();
    paintGateB();
  }

  function paintHeader() {
    const canCancel = can.cancel(user, task) && !TERMINAL_STATES.has(task.state);
    const key = JSON.stringify([task.state, task.updated_at, cancelArmed, canCancel]);
    if (memo.get('header') === key) return;
    memo.set('header', key);
    const cancelBtn = canCancel
      ? h('button', { class: 'btn btn-danger btn-sm', type: 'button', onclick: onCancel },
          cancelArmed ? 'Confirm cancel' : 'Cancel task')
      : null;
    headSlot.replaceChildren(...[
      h('div', { class: 'row', style: 'justify-content:space-between' },
        h('div', null,
          h('p', { class: 'kicker' }, 'Agent task'),
          h('h1', { tabindex: '-1' }, 'Mission ', h('span', { class: 'task-id' }, short(task.id, 8)))),
        h('div', { class: 'row' }, stateBadge(task.state, { large: true }), cancelBtn)),
      h('blockquote', { class: 'instruction' }, task.instruction || '(no instruction)'),
      h('div', { class: 'meta-list' },
        h('span', null, 'Requested by ', h('strong', { class: 'mono' }, (task.owner && task.owner.username) || 'unknown')),
        h('span', null, 'Dataset ', h('span', { class: 'mono' }, short(task.dataset_id, 8))),
        h('span', null, 'Created ', fmtDate(task.created_at)),
        h('span', null, 'Updated ', fmtDate(task.updated_at))),
      (task.requested_outputs && task.requested_outputs.length) ? chipList(task.requested_outputs) : null,
      task.error_reason ? alertBox('error', `Stopped: ${task.error_reason}`) : null].filter(Boolean));
  }

  function paintStepper() {
    const parent = derivedBranchParent(task);
    paint('stepper', JSON.stringify([task.state, parent]), () => [
      panelHead('Lifecycle', 'Gate A and gate B are human decisions. A dashed red branch marks where a task stopped.'),
      stateStepper(task.state, parent),
      h('p', { class: 'stepper-foot' }, (STATE_META[task.state] || {}).hint || ''),
    ]);
  }

  function paintPlan() {
    paint('plan', JSON.stringify([task.state, task.plan, task.error_reason]), () => {
      const plan = task.plan;
      const head = panelHead('Plan', 'From the planner, checked against the tool registry before anyone approves it.',
        plan && plan.data_class ? dataClassBadge(plan.data_class) : null);
      if (!plan) {
        if (task.state === 'PLANNING') return [head, spinner('The planner is drafting a plan…')];
        if (task.state === 'FAILED_PLANNING') {
          return [head, alertBox('error', task.error_reason || 'The model output did not match the plan schema, so no plan was produced.')];
        }
        return [head, emptyState('No plan', 'A plan appears here after planning.')];
      }
      const limits = plan.limits || {};
      return [
        head,
        h('h3', { class: 'small muted', style: 'margin:0 0 8px' }, 'Tools'),
        chipList(plan.tools || []),
        h('h3', { class: 'small muted', style: 'margin:16px 0 8px' }, 'Steps'),
        h('ol', { class: 'plan-steps' }, (plan.steps || []).map((s) => h('li', null,
          h('span', { class: 'sid' }, s.id),
          h('span', null, s.description),
          h('span', { class: 'tool' }, s.tool)))),
        h('h3', { class: 'small muted', style: 'margin:16px 0 8px' }, 'Resource limits (enforced by the sandbox)'),
        h('dl', { class: 'kv-grid' },
          kv('Timeout', limits.timeout_s != null ? `${limits.timeout_s} s` : '—'),
          kv('Memory', limits.memory_mb != null ? `${limits.memory_mb} MB` : '—'),
          kv('Processes (pids)', limits.pids ?? '—')),
        h('h3', { class: 'small muted', style: 'margin:16px 0 8px' }, 'Expected outputs'),
        chipList(plan.expected_outputs || []),
        (plan.assumptions && plan.assumptions.length)
          ? h('div', null,
              h('h3', { class: 'small muted', style: 'margin:16px 0 4px' }, 'Assumptions'),
              h('ul', { class: 'assumptions' }, plan.assumptions.map((a) => h('li', null, a))))
          : null,
      ];
    });
  }

  function gateControls(gate, verb) {
    const note = h('textarea', { id: `gate-${gate}-note`, rows: '2', placeholder: 'Optional. Recorded with your decision.' });
    const approve = h('button', { class: 'btn btn-primary btn-gate', type: 'button' }, verb.approve);
    const reject = h('button', { class: 'btn btn-danger', type: 'button' }, verb.reject);
    async function decide(decision) {
      approve.disabled = true;
      reject.disabled = true;
      try {
        await api.post(`agent/tasks/${enc(id)}/approve`, {
          gate,
          decision,
          note: note.value.trim() || undefined,
        }, { signal });
        toast(`Gate ${gate} ${decision === 'approve' ? 'approved' : 'rejected'}.`, { kind: 'success' });
      } catch (err) {
        fail(err);
      } finally {
        if (!signal.aborted) {
          approve.disabled = false;
          reject.disabled = false;
          scheduleRefresh(0);
        }
      }
    }
    approve.addEventListener('click', () => decide('approve'));
    reject.addEventListener('click', () => decide('reject'));
    return h('div', null,
      h('div', { class: 'field' },
        h('label', { class: 'label', for: `gate-${gate}-note` }, 'Note'),
        note),
      h('div', { class: 'gate-actions' }, approve, reject));
  }

  function decisionList(gate) {
    const items = (task.approvals || []).filter((a) => a.gate === gate);
    if (!items.length) return null;
    return h('ul', { class: 'decision-list', 'aria-label': `Gate ${gate} decisions` }, items.map((a) => h('li', null,
      h('div', null,
        h('strong', null, a.decision === 'approve' ? '✓ Approved' : '✕ Rejected'),
        ' by ',
        h('span', { class: 'who' }, `${(a.approver && a.approver.username) || 'unknown'} (${a.role || 'role n/a'})`),
        ' · ',
        fmtDate(a.at)),
      a.note ? h('div', { class: 'note' }, `Note: ${a.note}`) : null)));
  }

  function paintGateA() {
    const waiting = task.state === 'AWAITING_APPROVAL';
    const allowed = can.gateA(user, task);
    const key = JSON.stringify([task.state, task.approvals, user.role, user.id, task.owner && task.owner.id]);
    paint('gateA', key, () => {
      const head = panelHead('Gate A · Execution plan',
        'Approves the planned tools, dataset and resource limits before code is generated. It does not approve the generated code.',
        badge(waiting ? 'Waiting' : 'Decided', waiting ? 'warn' : 'neutral'));
      const who = h('p', { class: 'gate-note' },
        `Allowed: Approver or Admin, not the requester (${(task.owner && task.owner.username) || 'unknown'}).`);
      let body;
      if (waiting && allowed) {
        body = [who, gateControls('A', { approve: 'Approve plan and limits', reject: 'Reject plan' })];
      } else if (waiting && isOwner(user, task)) {
        body = [who, alertBox('info', 'You requested this task. A different Approver must decide gate A.')];
      } else if (waiting) {
        body = [who, alertBox('info', `Waiting for an Approver. Your role (${user.role}) cannot decide gate A.`)];
      } else if (task.state === 'REJECTED') {
        body = [alertBox('error', 'Rejected at gate A. No code ran.')];
      } else {
        body = [h('p', { class: 'gate-note' }, 'Gate A is closed for this task.')];
      }
      return [head, ...body, decisionList('A')];
    });
  }

  function paintCode() {
    const codeFile = artifacts.find((a) => a.name === 'task.py');
    const key = JSON.stringify([task.code_sha256, codeFile ? codeFile.id : null]);
    paint('code', key, () => {
      const head = panelHead('Generated code', 'Read-only. Generated after gate A, inside QUEUED.');
      if (!task.code_sha256) {
        return [head, alertBox('info', 'Not generated yet. Code is produced after gate A approves the plan.')];
      }
      const hashRow = h('div', { class: 'hash-row' },
        h('span', { class: 'hash', title: task.code_sha256 }, task.code_sha256),
        copyButton(task.code_sha256, 'Copy code SHA-256'));
      const parts = [head, h('p', { class: 'small muted', style: 'margin-bottom:8px' }, 'SHA-256 of task.py'), hashRow];
      if (codeFile) {
        const view = h('div', null);
        const load = h('button', { class: 'btn btn-sm', type: 'button' }, 'Show code');
        load.addEventListener('click', async () => {
          load.disabled = true;
          view.replaceChildren(spinner('Loading code…'));
          try {
            const { blob, sha256 } = await api.blob(`artifacts/${enc(codeFile.id)}`, { signal });
            const check = await verifyBlob(blob, task.code_sha256 || sha256 || codeFile.sha256);
            const text = await blob.text();
            const pre = h('pre', { class: 'code-block', tabindex: '0', 'aria-label': 'Generated code, read-only' }, text);
            view.replaceChildren(hashStatus(check), copyButton(text, 'Copy code'), pre);
          } catch (err) {
            if (signal.aborted) return;
            view.replaceChildren(alertBox('error', err.message));
            load.disabled = false;
          }
        });
        parts.push(h('div', { class: 'row', style: 'margin-top:12px' }, load), view);
      } else {
        parts.push(h('p', { class: 'hint', style: 'margin-top:12px' },
          'The API does not expose the script text, so only its SHA-256 is shown.'));
      }
      return parts;
    });
  }

  function flag(value, bad) {
    if (bad) {
      return value
        ? h('span', { class: 'badge badge--bad' }, '✕ Yes')
        : h('span', { class: 'badge badge--ok' }, '✓ No');
    }
    return h('span', { class: 'badge badge--neutral' }, value ? 'Yes' : 'No');
  }

  function paintSandbox() {
    paint('sandbox', JSON.stringify(task.sandbox), () => {
      const head = panelHead('Sandbox evidence', 'Reported by the sandbox runner for this run.');
      const sb = task.sandbox;
      if (!sb) {
        return [head, emptyState('No sandbox run yet', 'The sandbox starts when the task is RUNNING, after gate A and code generation.')];
      }
      const timeout = task.plan && task.plan.limits ? task.plan.limits.timeout_s : null;
      return [
        head,
        sb.runner === 'local'
          ? alertBox('warn', 'Local runner. Development only: there is no container isolation for this run.')
          : null,
        h('dl', { class: 'kv-grid', style: 'margin-top:12px' },
          h('div', { class: 'kv' }, h('dt', null, 'Runner'), h('dd', null, badge(sb.runner, sb.runner === 'local' ? 'warn' : 'neutral'))),
          kv('Container', sb.container_id || 'none (local runner)'),
          kv('Exit code', sb.exit_code ?? '—'),
          kv('Duration', `${fmtMs(sb.duration_ms)}${timeout != null ? ` of ${timeout} s limit` : ''}`),
          h('div', { class: 'kv' }, h('dt', null, 'Timed out'), h('dd', null, flag(sb.timed_out, true))),
          h('div', { class: 'kv' }, h('dt', null, 'OOM killed'), h('dd', null, flag(sb.oom_killed, true))),
          h('div', { class: 'kv' }, h('dt', null, 'stdout truncated'), h('dd', null, flag(sb.stdout_truncated, false))),
          h('div', { class: 'kv' }, h('dt', null, 'stderr truncated'), h('dd', null, flag(sb.stderr_truncated, false)))),
        h('details', null,
          h('summary', null, 'stdout excerpt'),
          h('pre', { class: 'code-block', tabindex: '0' }, sb.stdout_excerpt || '(empty)')),
        h('details', null,
          h('summary', null, 'stderr excerpt'),
          h('pre', { class: 'code-block', tabindex: '0' }, sb.stderr_excerpt || '(empty)')),
      ];
    });
  }

  // Thumbnails and downloads. Images are fetched through the API and hash-checked before display.
  async function loadThumb(a, img, status) {
    try {
      const { blob, sha256 } = await api.blob(`artifacts/${enc(a.id)}`, { signal });
      const check = await verifyBlob(blob, a.sha256 || sha256);
      if (signal.aborted) return;
      status.replaceChildren(hashStatus(check));
      if (check.status === 'mismatch') {
        img.replaceWith(alertBox('error', 'Image hash does not match. It is not shown.'));
        return;
      }
      const url = URL.createObjectURL(blob);
      blobUrls.push(url);
      img.src = url;
      img.hidden = false;
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      status.replaceChildren(alertBox('error', err.message));
    }
  }

  function artifactCard(a) {
    const isImage = a.type === 'png';
    const status = h('div', { class: 'row' });
    const img = isImage ? h('img', { alt: `Chart image ${a.name}, generated in the sandbox`, hidden: true, loading: 'lazy' }) : null;
    const verifyBtn = !isImage
      ? h('button', { class: 'btn btn-sm', type: 'button' }, 'Verify hash')
      : null;
    if (verifyBtn) {
      verifyBtn.addEventListener('click', async () => {
        verifyBtn.disabled = true;
        try {
          const { blob, sha256 } = await api.blob(`artifacts/${enc(a.id)}`, { signal });
          status.replaceChildren(hashStatus(await verifyBlob(blob, a.sha256 || sha256)));
        } catch (err) {
          if (!signal.aborted) status.replaceChildren(alertBox('error', err.message));
        } finally {
          if (!signal.aborted) verifyBtn.disabled = false;
        }
      });
    }
    const card = h('article', { class: 'artifact-card' },
      img ? h('div', null, img, h('p', { class: 'hint', style: 'margin-top:6px' }, 'Thumbnail')) : null,
      h('div', { class: 'row', style: 'justify-content:space-between' },
        h('span', { class: 'artifact-name' }, a.name),
        h('span', { class: 'row' }, badge(String(a.type || '').toUpperCase(), 'neutral'), dataClassBadge('SIMULATED_FACT'))),
      h('div', { class: 'small muted' }, `${fmtBytes(a.size_bytes)} · ${fmtDate(a.created_at)}`),
      h('div', { class: 'hash-row' },
        h('span', { class: 'hash', title: a.sha256 || '' }, short(a.sha256, 18)),
        a.sha256 ? copyButton(a.sha256, `Copy SHA-256 of ${a.name}`) : null),
      status,
      h('div', { class: 'artifact-actions' },
        h('a', { class: 'btn btn-sm', href: `api/artifacts/${enc(a.id)}`, download: a.name }, 'Download'),
        verifyBtn));
    if (isImage) loadThumb(a, img, status);
    return card;
  }

  function paintArtifacts() {
    const key = JSON.stringify([task.state, artifacts.map((a) => `${a.id}:${a.sha256}`)]);
    paint('artifacts', key, () => {
      const head = panelHead('Artifacts', 'Server-named files with SHA-256 hashes. Results are SIMULATED_FACT until gate B.',
        dataClassBadge('SIMULATED_FACT'));
      const status = h('p', { class: 'small muted', style: 'margin-bottom:12px' }, VALIDATION_TEXT[task.state] || '—');
      if (!artifacts.length) return [head, status, emptyState('No artifacts', 'Files appear here after the sandbox run and validation.')];
      return [head, status, h('div', { class: 'artifact-grid' }, artifacts.map(artifactCard))];
    });
  }

  function paintGateB() {
    const waiting = task.state === 'AWAITING_REVIEW';
    const allowed = can.gateB(user, task);
    const key = JSON.stringify([task.state, task.approvals, user.role, user.id, task.owner && task.owner.id]);
    paint('gateB', key, () => {
      const head = panelHead('Gate B · Report release',
        'A reviewer releases validated outputs. Until then they are not results.',
        badge(waiting ? 'Waiting' : 'Decided', waiting ? 'warn' : 'neutral'));
      const who = h('p', { class: 'gate-note' },
        `Allowed: Reviewer or higher, not the requester (${(task.owner && task.owner.username) || 'unknown'}).`);
      let body;
      if (waiting && allowed) {
        body = [who, gateControls('B', { approve: 'Release outputs', reject: 'Reject outputs' })];
      } else if (waiting && isOwner(user, task)) {
        body = [who, alertBox('info', 'You requested this task. A different reviewer must release the outputs.')];
      } else if (waiting) {
        body = [who, alertBox('info', `Waiting for a Reviewer. Your role (${user.role}) cannot release outputs.`)];
      } else if (task.state === 'COMPLETED') {
        body = [alertBox('ok', 'Outputs released at gate B.')];
      } else if (task.state === 'REJECTED_OUTPUT') {
        body = [alertBox('error', 'Outputs failed validation. Gate B was not reached.')];
      } else {
        body = [h('p', { class: 'gate-note' }, 'Gate B opens after outputs are validated.')];
      }
      return [head, ...body, decisionList('B')];
    });
  }

  async function onCancel() {
    if (!cancelArmed) {
      cancelArmed = true;
      paintHeader();
      clearTimeout(cancelTimer);
      cancelTimer = setTimeout(() => {
        cancelArmed = false;
        if (!signal.aborted && task) paintHeader();
      }, 4000);
      return;
    }
    cancelArmed = false;
    clearTimeout(cancelTimer);
    try {
      await api.postEmpty(`agent/tasks/${enc(id)}/cancel`, { signal });
      toast('Cancel requested.', { kind: 'success' });
    } catch (err) {
      fail(err);
    } finally {
      if (!signal.aborted) scheduleRefresh(0);
    }
  }

  // ---------- Live stream (SSE) ----------
  function parse(event) {
    try {
      return JSON.parse(event.data);
    } catch {
      return null;
    }
  }

  function closeStream() {
    if (es) {
      es.close();
      es = null;
    }
  }

  function scheduleReconnect() {
    if (ended || signal.aborted || paused) return;
    const delay = Math.min(RECONNECT_MAX_MS, 1000 * 2 ** retries);
    retries += 1;
    term.setStatus(`RECONNECTING IN ${Math.round(delay / 1000)}s`);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, delay);
  }

  function connect() {
    if (ended || signal.aborted || paused) return;
    clearTimeout(reconnectTimer);
    closeStream();
    term.setStatus('CONNECTING');
    es = new EventSource(`api/agent/tasks/${enc(id)}/events`, { withCredentials: true });

    es.onopen = () => {
      retries = 0;
      term.setStatus('LIVE', true);
    };
    es.addEventListener('state', (e) => {
      const d = parse(e);
      if (!d) return;
      term.note(`state -> ${d.state}`, d.at);
      scheduleRefresh();
    });
    es.addEventListener('log', (e) => {
      const d = parse(e);
      if (!d) return;
      term.append({ stream: d.stream === 'stderr' ? 'stderr' : 'stdout', line: d.line, at: d.at });
    });
    es.addEventListener('gate', (e) => {
      const d = parse(e);
      if (!d) return;
      term.note(`gate ${d.gate}: ${d.status}`);
      scheduleRefresh();
    });
    es.addEventListener('end', (e) => {
      const d = parse(e);
      ended = true;
      closeStream();
      term.note(`end: ${(d && d.state) || 'closed'}`);
      term.setStatus('ENDED');
      scheduleRefresh(0);
      const finalState = (d && d.state) || (task && task.state);
      const ok = finalState === 'COMPLETED';
      toast(`Task finished: ${(STATE_META[finalState] || { label: finalState }).label}`, { kind: ok ? 'success' : 'info' });
    });
    es.onerror = () => {
      if (ended || signal.aborted) return;
      closeStream();
      if (task && TERMINAL_STATES.has(task.state)) {
        ended = true;
        term.setStatus('CLOSED');
        return;
      }
      scheduleReconnect();
    };
  }

  // Keep the stream only while the page is visible.
  function onVisibility() {
    if (document.hidden) {
      paused = true;
      clearTimeout(reconnectTimer);
      closeStream();
      term.setStatus('PAUSED (tab hidden)');
    } else if (paused) {
      paused = false;
      if (!ended && !signal.aborted) {
        term.note('Tab visible again. Reconnecting and refreshing state.');
        scheduleRefresh(0);
        connect();
      }
    }
  }
  document.addEventListener('visibilitychange', onVisibility);

  // ---------- Start ----------
  try {
    await fetchAll();
  } catch (err) {
    if (!signal.aborted && err.name !== 'AbortError') {
      headSlot.replaceChildren(errorState(err, () => go(`#/tasks/${enc(id)}`)));
    }
    return cleanup();
  }
  if (document.hidden) onVisibility();
  else connect();

  function cleanup() {
    closeStream();
    clearTimeout(reconnectTimer);
    clearTimeout(refreshTimer);
    clearTimeout(cancelTimer);
    document.removeEventListener('visibilitychange', onVisibility);
    blobUrls.forEach((u) => URL.revokeObjectURL(u));
    blobUrls.length = 0;
    clear(root);
  }

  return cleanup;
}
