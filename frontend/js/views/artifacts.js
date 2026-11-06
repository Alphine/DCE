import { api } from '../api.js';
import { h, listOf, pageHead, panel, emptyState, spinner, alertBox, short, fmtDate, fmtBytes } from '../dom.js';
import { stateBadge, dataClassBadge, badge } from '../components/badges.js';
import { copyButton } from '../components/copy.js';
import { verifyBlob, hashStatus, canHash } from '../components/hash.js';

const MAX_TASKS = 30;
const enc = encodeURIComponent;

// ctx: { signal }. Shows artifacts of tasks the user can read (own tasks; all tasks for Reviewer+).
export async function mount(root, ctx) {
  const { signal } = ctx;
  const blobUrls = [];
  const gallerySlot = h('div', null, spinner('Loading artifacts…'));
  const tableSlot = h('div', null);

  root.append(
    pageHead('Artifacts',
      'Charts and reports produced by the sandbox. Each file has a server-recorded SHA-256. Results are SIMULATED_FACT until a reviewer releases them.'),
    h('div', { class: 'stack' },
      panel({ title: 'Verification', style: '--i:1' },
        h('p', { class: 'small muted' },
          'Download and verify a file here: the browser computes its SHA-256 and compares it with the server record. ',
          canHash
            ? 'Web Crypto is available in this context.'
            : 'Web Crypto is not available here. Open the app over HTTPS or localhost to verify hashes.')),
      panel({ title: 'Chart gallery', sub: 'PNG files, thumbnails hash-checked before display.', style: '--i:2' }, gallerySlot),
      panel({ title: 'All files', sub: 'Newest first. A file from a task that is not COMPLETED has not been released.', style: '--i:3' }, tableSlot)));

  async function load() {
    try {
      const tasks = listOf(await api.get('agent/tasks', { signal }))
        .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
        .slice(0, MAX_TASKS);
      const results = await Promise.allSettled(tasks.map((t) =>
        api.get(`agent/tasks/${enc(t.id)}/artifacts`, { signal }).then((list) => ({ task: t, files: listOf(list) }))));
      if (signal.aborted) return;
      const rows = [];
      for (const r of results) {
        if (r.status === 'fulfilled') for (const f of r.value.files) rows.push({ task: r.value.task, file: f });
      }
      render(rows);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      gallerySlot.replaceChildren(alertBox('error', err.message));
    }
  }

  function render(rows) {
    rows.sort((a, b) => String(b.file.created_at).localeCompare(String(a.file.created_at)));
    const pngs = rows.filter((r) => r.file.type === 'png');
    gallerySlot.replaceChildren(pngs.length
      ? h('div', { class: 'artifact-grid' }, pngs.map((r) => thumbCard(r)))
      : emptyState('No charts yet', 'PNG charts appear here after a sandbox run produces them.'));
    tableSlot.replaceChildren(rows.length ? table(rows) : emptyState('No files yet', 'Artifacts from your tasks appear here.'));
  }

  function thumbCard({ task, file }) {
    const status = h('div', { class: 'row' });
    const img = h('img', { alt: `Chart ${file.name} from task ${short(task.id, 8)}`, hidden: true, loading: 'lazy' });
    const card = h('article', { class: 'artifact-card' },
      h('div', null, img),
      h('div', { class: 'row', style: 'justify-content:space-between' },
        h('span', { class: 'artifact-name' }, file.name),
        dataClassBadge('SIMULATED_FACT')),
      h('div', { class: 'small muted' }, `Task ${short(task.id, 8)} · ${fmtBytes(file.size_bytes)}`),
      status);
    (async () => {
      try {
        const { blob, sha256 } = await api.blob(`artifacts/${enc(file.id)}`, { signal });
        const check = await verifyBlob(blob, file.sha256 || sha256);
        if (signal.aborted) return;
        status.replaceChildren(hashStatus(check));
        if (check.status === 'mismatch') {
          img.replaceWith(alertBox('error', 'Hash mismatch. This image is not shown.'));
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
    })();
    return card;
  }

  function table(rows) {
    return h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Artifact files'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'File'),
          h('th', { scope: 'col' }, 'Type'),
          h('th', { scope: 'col', class: 'num' }, 'Size'),
          h('th', { scope: 'col' }, 'SHA-256'),
          h('th', { scope: 'col' }, 'Task'),
          h('th', { scope: 'col' }, 'Release'),
          h('th', { scope: 'col' }, 'Actions'))),
        h('tbody', null, rows.map((r) => fileRow(r)))));
  }

  function fileRow({ task, file }) {
    const verifyStatus = h('span', null);
    const verifyBtn = h('button', { class: 'btn btn-sm', type: 'button' }, 'Verify');
    verifyBtn.addEventListener('click', async () => {
      verifyBtn.disabled = true;
      try {
        const { blob, sha256 } = await api.blob(`artifacts/${enc(file.id)}`, { signal });
        verifyStatus.replaceChildren(hashStatus(await verifyBlob(blob, file.sha256 || sha256)));
      } catch (err) {
        if (!signal.aborted) verifyStatus.replaceChildren(alertBox('error', err.message));
      } finally {
        if (!signal.aborted) verifyBtn.disabled = false;
      }
    });
    const released = task.state === 'COMPLETED';
    return h('tr', null,
      h('td', { class: 'mono wrap-any' }, file.name),
      h('td', null, badge(String(file.type || '').toUpperCase(), 'neutral')),
      h('td', { class: 'num' }, fmtBytes(file.size_bytes)),
      h('td', null,
        h('div', { class: 'hash-row' },
          h('span', { class: 'hash', title: file.sha256 || '' }, short(file.sha256, 14)),
          file.sha256 ? copyButton(file.sha256, `Copy SHA-256 of ${file.name}`) : null),
        verifyStatus),
      h('td', { class: 'mono' }, short(task.id, 8)),
      h('td', null, released ? badge('Released', 'ok') : h('span', { class: 'row' }, stateBadge(task.state), h('span', { class: 'small muted' }, 'not released'))),
      h('td', null, h('div', { class: 'artifact-actions' },
        h('a', { class: 'btn btn-sm', href: `api/artifacts/${enc(file.id)}`, download: file.name }, 'Download'),
        verifyBtn)));
  }

  load();

  return () => {
    blobUrls.forEach((u) => URL.revokeObjectURL(u));
    blobUrls.length = 0;
  };
}
