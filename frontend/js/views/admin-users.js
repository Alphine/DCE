import { api } from '../api.js';
import { h, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, fmtDate } from '../dom.js';
import { toast } from '../components/toast.js';
import { hasRole } from '../session.js';

// Admin user page (Admin only). Sets role, status, email, and a new password for each account.
// Nothing here sends email. The email is a contact and identifier until a delivery service is added.

export const ROLES = ['Viewer', 'Analyst', 'Reviewer', 'Approver', 'Admin'];
export const PASSWORD_MIN = 12;
const EMAIL_RE = /^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

// Empty means "no email". Otherwise the address must look valid and be at most 254 characters.
export function emailProblem(value) {
  const v = (value || '').trim();
  if (v === '') return null;
  if (v.length > 254) return 'Keep the email under 254 characters.';
  if (!EMAIL_RE.test(v)) return 'Enter a valid email address, for example name@example.com.';
  return null;
}

export function passwordProblem(first, second) {
  if (!first) return 'Enter the new password.';
  if (first.length < PASSWORD_MIN) return `The password must be at least ${PASSWORD_MIN} characters.`;
  if (first !== second) return 'The two passwords do not match.';
  return null;
}

// Sends only the fields that changed. Email is sent as null when it is cleared.
export function userPatch(original, edited) {
  const body = {};
  if (edited.role !== original.role) body.role = edited.role;
  const disabled = edited.status === 'disabled';
  if (disabled !== (original.status === 'disabled')) body.disabled = disabled;
  const newEmail = (edited.email || '').trim().toLowerCase() || null;
  if (newEmail !== (original.email || null)) body.email = newEmail;
  return body;
}

export async function mount(root, ctx) {
  const { user, signal } = ctx;
  if (!hasRole(user, 'Admin')) {
    root.append(pageHead('Users', ''), panel({ title: 'Admin role needed', style: '--i:1' },
      alertBox('info', 'Only an Admin can manage accounts.')));
    return;
  }

  root.append(pageHead('Users',
    'Set each account\'s role, contact email, and status. A new password signs that person out everywhere.'));
  const listSlot = h('div', null, spinner('Loading accounts…'));
  root.append(panel({ title: 'Accounts', sub: 'Changes apply when you press Save on the row.', style: '--i:1' }, listSlot));

  async function load() {
    listSlot.replaceChildren(spinner('Loading accounts…'));
    try {
      const users = listOf(await api.get('admin/users', { signal }));
      if (signal.aborted) return;
      render(users);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      listSlot.replaceChildren(errorState(err, load));
    }
  }

  function render(users) {
    if (!users.length) {
      listSlot.replaceChildren(emptyState('No accounts', 'Create accounts from the command line on the server.'));
      return;
    }
    listSlot.replaceChildren(h('div', { class: 'table-wrap' },
      h('table', { class: 'table admin-users' },
        h('caption', { class: 'sr-only' }, 'Accounts'),
        h('thead', null, h('tr', null,
          h('th', { scope: 'col' }, 'Username'),
          h('th', { scope: 'col' }, 'Role'),
          h('th', { scope: 'col' }, 'Email'),
          h('th', { scope: 'col' }, 'Status'),
          h('th', { scope: 'col' }, 'Created'),
          h('th', { scope: 'col' }, 'Actions'))),
        h('tbody', null, users.map((u) => userRow(u))))));
  }

  function userRow(u) {
    const isSelf = u.id === user.id;
    const role = h('select', { 'aria-label': `Role for ${u.username}` },
      ROLES.map((r) => h('option', { value: r, selected: r === u.role ? true : undefined }, r)));
    role.value = u.role;
    const email = h('input', { type: 'email', 'aria-label': `Email for ${u.username}`, value: u.email || '',
      placeholder: 'No email yet', maxlength: '254', autocomplete: 'off' });
    const status = h('select', { 'aria-label': `Status for ${u.username}` },
      h('option', { value: 'active' }, 'Active'),
      h('option', { value: 'disabled' }, 'Disabled'));
    status.value = u.status;
    const rowErr = h('div', { 'aria-live': 'polite', class: 'row-err' });
    const save = h('button', { class: 'btn btn-primary btn-sm', type: 'button' }, 'Save');
    save.addEventListener('click', async () => {
      rowErr.replaceChildren();
      const edited = { role: role.value, status: status.value, email: email.value };
      const problem = emailProblem(email.value);
      if (problem) { rowErr.replaceChildren(alertBox('error', problem)); return; }
      const body = userPatch(u, edited);
      if (!Object.keys(body).length) { toast('Nothing to save.'); return; }
      save.disabled = true;
      try {
        await api.patch(`admin/users/${encodeURIComponent(u.id)}`, body, { signal });
        toast(`Saved ${u.username}.`);
        await load();
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') return;
        rowErr.replaceChildren(alertBox('error', err.message));
      } finally {
        save.disabled = false;
      }
    });

    return h('tr', null,
      h('td', { class: 'mono' }, u.username, isSelf ? h('span', { class: 'small muted' }, ' (you)') : null),
      h('td', null, role),
      h('td', null, email),
      h('td', null, status),
      h('td', { class: 'small' }, fmtDate(u.created_at)),
      h('td', { class: 'admin-actions' },
        h('div', { class: 'row' }, save),
        passwordForm(u),
        rowErr));
  }

  function passwordForm(u) {
    const first = h('input', { type: 'password', 'aria-label': `New password for ${u.username}`,
      autocomplete: 'new-password', minlength: String(PASSWORD_MIN) });
    const second = h('input', { type: 'password', 'aria-label': `Repeat new password for ${u.username}`,
      autocomplete: 'new-password', minlength: String(PASSWORD_MIN) });
    const err = h('div', { 'aria-live': 'polite' });
    const go = h('button', { class: 'btn btn-sm', type: 'button' }, 'Set password');
    go.addEventListener('click', async () => {
      err.replaceChildren();
      const problem = passwordProblem(first.value, second.value);
      if (problem) { err.replaceChildren(alertBox('error', problem)); return; }
      go.disabled = true;
      try {
        await api.post(`admin/users/${encodeURIComponent(u.id)}/password`, { new_password: first.value }, { signal });
        toast(`Password set for ${u.username}. Tell them through a safe channel.`);
        first.value = '';
        second.value = '';
        await load();
      } catch (error) {
        if (signal.aborted || error.name === 'AbortError') return;
        err.replaceChildren(alertBox('error', error.message));
      } finally {
        go.disabled = false;
      }
    });
    return h('details', { class: 'admin-password' },
      h('summary', null, 'Set a new password'),
      h('div', { class: 'stack' },
        h('label', { class: 'small' }, 'New password (at least 12 characters)', first),
        h('label', { class: 'small' }, 'Repeat new password', second),
        err,
        h('div', { class: 'row' }, go)));
  }

  await load();
}
