import { api } from '../api.js';
import { h, fmtDate, fmtBytes, short, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { datasetStatusBadge, dataClassBadge } from '../components/badges.js';
import { copyButton } from '../components/copy.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';
import { can, isOwner, hasRole } from '../session.js';
import { loadList, cacheNotice } from '../offline/read-cache.js';

const MAX_BYTES = 10 * 1024 * 1024; // 10 MB, matches docs/api.md §3

export function validateCsv(file) {
  if (!file) return 'Choose a CSV file first.';
  if (!/\.csv$/i.test(file.name)) return 'Only CSV files are accepted.';
  if (file.size === 0) return 'The file is empty.';
  if (file.size > MAX_BYTES) return `The file is ${fmtBytes(file.size)}. The limit is 10 MB.`;
  return null;
}

// ctx: { user, params, signal, navigate }
export async function mount(root, ctx) {
  const { user, params, signal } = ctx;
  const selectedId = params.id || null;
  const listSlot = h('div', null, spinner('Loading datasets…'));
  const detailSlot = h('div', { class: 'stack' });

  const parts = [
    pageHead('Datasets',
      'Upload CSV incident data, then a reviewer approves it. The agent can only use approved datasets.'),
  ];
  if (can.upload(user)) parts.push(uploadPanel());
  parts.push(panel({ title: 'All datasets', sub: 'Newest first. Open a row for its profile.', style: '--i:2' }, listSlot));
  parts.push(detailSlot);
  root.append(...parts);

  async function refreshList() {
    try {
      const { items: datasets, savedAt } = await loadList('datasets', 'datasets', { signal });
      if (signal.aborted) return;
      renderList(datasets);
      if (savedAt) listSlot.prepend(cacheNotice(savedAt));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, refreshList));
    }
  }

  function renderList(datasets) {
    if (!datasets.length) {
      listSlot.replaceChildren(emptyState('No datasets yet', hasRole(user, 'Analyst') ? 'Upload a CSV above to start.' : 'An analyst needs to upload one.',
        { icon: 'datasets', actions: [{ label: 'Open Reports', href: '#/reports' }] }));
      return;
    }
    const sorted = [...datasets].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('caption', { class: 'sr-only' }, 'Datasets'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Name'),
          h('th', { scope: 'col' }, 'File'),
          h('th', { scope: 'col', class: 'num' }, 'Size'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Uploaded by'),
          h('th', { scope: 'col' }, 'Uploaded'))),
        h('tbody', null, sorted.map((d) => h('tr', { class: 'row-link' },
          h('td', { class: 'wrap-any' }, h('a', { href: `#/datasets/${encodeURIComponent(d.id)}` }, d.name || d.filename)),
          h('td', { class: 'mono wrap-any' }, d.filename),
          h('td', { class: 'num' }, fmtBytes(d.size_bytes)),
          h('td', null, datasetStatusBadge(d.status)),
          h('td', null, (d.owner && d.owner.username) || '—'),
          h('td', null, fmtDate(d.created_at))))))));
  }

  // Upload: drag and drop plus file picker, with client-side CSV and 10 MB checks.
  function uploadPanel() {
    const nameInput = h('input', { id: 'ds-name', type: 'text', maxlength: '120', placeholder: 'Optional. Defaults to the file name' });
    const picked = h('p', { class: 'small muted', 'aria-live': 'polite' }, 'No file chosen. CSV only, UTF-8 with a header row, up to 10 MB.');
    const errorSlot = h('div');
    const submit = h('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Upload dataset');
    const fileInput = h('input', { id: 'ds-file', type: 'file', accept: '.csv,text/csv', class: 'sr-only' });
    const zone = h('div', { class: 'dropzone', tabindex: '-1' },
      h('div', { class: 'dropzone-glyph', 'aria-hidden': 'true' }, '↓'),
      h('p', null, h('strong', null, 'Drop a CSV here'), ' or'),
      h('label', { class: 'btn btn-sm', for: 'ds-file' }, 'Choose file'),
      picked);
    let file = null;

    function setFile(f) {
      file = f || null;
      errorSlot.replaceChildren();
      const problem = validateCsv(file);
      if (problem) {
        errorSlot.replaceChildren(alertBox('error', problem));
        file = null;
        picked.textContent = 'No file chosen. CSV only, up to 10 MB.';
        zone.classList.remove('has-file');
      } else {
        picked.textContent = `${file.name} · ${fmtBytes(file.size)}`;
        zone.classList.add('has-file');
      }
      submit.disabled = !file;
    }

    fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.add('is-over');
    }));
    ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.remove('is-over');
    }));
    zone.addEventListener('drop', (e) => {
      const dropped = e.dataTransfer && e.dataTransfer.files[0];
      if (dropped) setFile(dropped);
    });

    async function onSubmit(event) {
      event.preventDefault();
      if (!file) return;
      submit.disabled = true;
      submit.textContent = 'Uploading…';
      try {
        const fd = new FormData();
        fd.append('file', file, file.name);
        const name = nameInput.value.trim();
        if (name) fd.append('name', name);
        const created = await api.upload('datasets', fd, { signal });
        if (signal.aborted) return;
        toast('Dataset uploaded. A reviewer must approve it before the agent can use it.', { kind: 'success' });
        if (created && created.id) go(`#/datasets/${encodeURIComponent(created.id)}`);
        else refreshList();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        errorSlot.replaceChildren(alertBox('error', err.message));
        toast(err.message, { kind: 'error' });
      } finally {
        submit.textContent = 'Upload dataset';
        submit.disabled = !file;
      }
    }

    return panel({ title: 'Upload dataset', sub: 'Analyst role or higher.', style: '--i:1' },
      h('form', { onsubmit: onSubmit, 'aria-label': 'Upload CSV dataset' },
        h('div', { class: 'field-row' },
          h('div', { class: 'field' },
            h('label', { class: 'label', for: 'ds-name' }, 'Display name'),
            nameInput),
          h('div', { class: 'field' },
            h('span', { class: 'label' }, 'CSV file'),
            zone)),
        fileInput,
        errorSlot,
        h('div', { class: 'row' }, submit,
          h('span', { class: 'hint' }, 'The file is checked again on the server. The client checks are a convenience.'))));
  }

  // Detail: metadata, profile, and the approval control.
  async function loadDetail(id) {
    detailSlot.replaceChildren(panel({ title: 'Dataset detail', style: '--i:3' }, spinner('Loading dataset…')));
    try {
      const ds = await api.get(`datasets/${encodeURIComponent(id)}`, { signal });
      if (signal.aborted) return;
      renderDetail(ds);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      detailSlot.replaceChildren(panel({ title: 'Dataset detail' }, errorState(err, () => loadDetail(id))));
    }
  }

  function renderDetail(ds) {
    const profile = ds.profile || {};
    const columns = profile.columns || [];
    const preview = profile.preview || [];
    const pending = ds.status === 'PENDING_VALIDATION';
    const approvalSlot = h('div', { class: 'stack' });

    const approveBtn = h('button', { class: 'btn btn-primary btn-gate', type: 'button' }, 'Approve dataset');
    const confirmBtn = h('button', { class: 'btn btn-primary btn-gate', type: 'button', hidden: true }, 'Confirm approval');
    const cancelBtn = h('button', { class: 'btn btn-ghost', type: 'button', hidden: true }, 'Cancel');
    const approvalMsg = h('div', { 'aria-live': 'polite' });

    function showApprovalState() {
      approvalSlot.replaceChildren();
      if (!pending) {
        approvalSlot.append(alertBox(ds.status === 'APPROVED' ? 'ok' : 'warn',
          ds.status === 'APPROVED' ? 'Approved. The agent can use this dataset.' : `Status: ${ds.status}. Only approved datasets can be used by the agent.`));
        return;
      }
      if (can.approveDataset(user, ds)) {
        approvalSlot.append(
          h('p', { class: 'hint' }, 'Approving confirms the dataset may be used by the agent. You cannot approve a dataset you uploaded.'),
          h('div', { class: 'row' }, approveBtn, confirmBtn, cancelBtn),
          approvalMsg);
      } else if (isOwner(user, ds)) {
        approvalSlot.append(alertBox('info', 'You uploaded this dataset. Another reviewer must approve it.'));
      } else {
        approvalSlot.append(alertBox('info', 'Approval needs the Reviewer role. Ask a reviewer to approve this dataset.'));
      }
    }

    // Two-step confirm: first press reveals the confirm button.
    approveBtn.addEventListener('click', () => {
      approveBtn.hidden = true;
      confirmBtn.hidden = false;
      cancelBtn.hidden = false;
      confirmBtn.focus();
    });
    cancelBtn.addEventListener('click', () => {
      confirmBtn.hidden = true;
      cancelBtn.hidden = true;
      approveBtn.hidden = false;
      approveBtn.focus();
    });
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      try {
        await api.postEmpty(`datasets/${encodeURIComponent(ds.id)}/approve`, { signal });
        if (signal.aborted) return;
        toast('Dataset approved.', { kind: 'success' });
        await loadDetail(ds.id);
        refreshList();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        // SELF_APPROVAL_NOT_ALLOWED arrives here too: show the server message inline and in a toast.
        approvalMsg.replaceChildren(alertBox('error', err.message));
        toast(err.message, { kind: 'error' });
        confirmBtn.disabled = false;
      }
    });
    showApprovalState();

    detailSlot.replaceChildren(panel({
      title: ds.name || ds.filename,
      sub: `${ds.filename} · ${fmtBytes(ds.size_bytes)} · uploaded ${fmtDate(ds.created_at)}`,
      actions: [datasetStatusBadge(ds.status), dataClassBadge('RAW_REPORT')],
      style: '--i:3',
    },
      h('dl', { class: 'kv-grid' },
        kv('Rows', profile.rows ?? '—'),
        kv('Owner', (ds.owner && ds.owner.username) || '—'),
        h('div', { class: 'kv' }, h('dt', null, 'SHA-256'),
          h('dd', { class: 'hash-row' },
            h('span', { class: 'hash', title: ds.sha256 || '' }, short(ds.sha256, 24)),
            ds.sha256 ? copyButton(ds.sha256, 'Copy dataset SHA-256') : null))),
      h('div', { class: 'stack', style: 'margin-top:16px' }, approvalSlot),
      h('h3', { style: 'margin:22px 0 10px;font-size:.95rem' }, 'Profile'),
      columns.length
        ? h('div', { class: 'table-wrap' },
            h('table', { class: 'table' },
              h('caption', { class: 'sr-only' }, 'Column profile'),
              h('thead', null, h('tr', null,
                h('th', { scope: 'col' }, 'Column'),
                h('th', { scope: 'col' }, 'Type'),
                h('th', { scope: 'col', class: 'num' }, 'Nulls'))),
              h('tbody', null, columns.map((c) => h('tr', null,
                h('td', { class: 'mono' }, c.name),
                h('td', { class: 'mono' }, c.dtype),
                h('td', { class: 'num' }, String(c.nulls ?? 0)))))))
        : emptyState('No column profile', 'The server returned no columns for this dataset.'),
      h('h3', { style: 'margin:22px 0 10px;font-size:.95rem' }, 'Preview'),
      preview.length
        ? h('div', { class: 'table-wrap' }, previewTable(columns, preview))
        : emptyState('No preview rows', 'The dataset has no preview rows.'),
      h('p', { class: 'hint', style: 'margin-top:10px' }, `Showing up to 5 rows of ${profile.rows ?? 'unknown'} from the server profile.`)));
  }

  function previewTable(columns, rows) {
    const names = columns.length ? columns.map((c) => c.name) : Object.keys(rows[0] || {});
    return h('table', { class: 'table' },
      h('caption', { class: 'sr-only' }, 'Dataset preview'),
      h('thead', null, h('tr', null, names.map((n) => h('th', { scope: 'col', class: 'mono' }, n)))),
      h('tbody', null, rows.map((r) => h('tr', null, names.map((n) => h('td', { class: 'mono' }, r[n] === null || r[n] === undefined ? '∅' : String(r[n])))))));
  }

  refreshList();
  if (selectedId) loadDetail(selectedId);
  return () => {};
}
