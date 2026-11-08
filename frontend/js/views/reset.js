import { api } from '../api.js';
import { h, alertBox } from '../dom.js';
import { parseHash } from '../router.js';

// Public page reached from the emailed link: #/reset?token=... Sets a new password once, then asks to sign in.
export const RESET_PASSWORD_MIN = 12;

// Returns a client-side message, or null when the form can be sent. The server checks everything again.
export function resetProblem(token, first, second) {
  if (!token) return 'This link has no reset token. Open the link from the email again.';
  if (!first) return 'Enter the new password.';
  if (first.length < RESET_PASSWORD_MIN) return `The password must be at least ${RESET_PASSWORD_MIN} characters.`;
  if (first !== second) return 'The two passwords do not match.';
  return null;
}

// ctx: { signal, navigate } provided by app.js.
export async function mount(root, ctx) {
  const token = parseHash().query.get('token') || '';
  const errorSlot = h('div', { 'aria-live': 'polite' });
  const first = h('input', { id: 'rs-pass', type: 'password', autocomplete: 'new-password', required: true,
    minlength: String(RESET_PASSWORD_MIN) });
  const second = h('input', { id: 'rs-pass2', type: 'password', autocomplete: 'new-password', required: true,
    minlength: String(RESET_PASSWORD_MIN) });
  const submit = h('button', { class: 'btn btn-primary btn-block btn-gate', type: 'submit' }, 'Save new password');

  async function onSubmit(event) {
    event.preventDefault();
    errorSlot.replaceChildren();
    const problem = resetProblem(token, first.value, second.value);
    if (problem) { errorSlot.replaceChildren(alertBox('error', problem)); return; }
    submit.disabled = true;
    try {
      await api.post('auth/reset', { token, new_password: first.value }, { signal: ctx.signal, suppressAuthEvent: true });
      if (ctx.signal.aborted) return;
      root.replaceChildren(done());
    } catch (err) {
      if (ctx.signal.aborted || err.name === 'AbortError') return;
      errorSlot.replaceChildren(alertBox('error', err.message));
      submit.disabled = false;
    }
  }

  function done() {
    return h('div', { class: 'login' }, h('div', { class: 'login-wrap' },
      h('section', { class: 'login-card panel' },
        h('h2', { class: 'panel-title' }, 'Password changed'),
        h('p', { class: 'panel-sub' }, 'Your new password is saved. Every older session has ended.'),
        h('a', { class: 'btn btn-primary btn-block btn-gate', href: '#/login' }, 'Sign in'))));
  }

  const form = h('form', { class: 'login-card panel', onsubmit: onSubmit, 'aria-labelledby': 'reset-title' },
    h('h2', { id: 'reset-title', class: 'panel-title' }, 'Choose a new password'),
    h('p', { class: 'panel-sub' }, `At least ${RESET_PASSWORD_MIN} characters. The link works once and expires after 30 minutes.`),
    h('div', { class: 'field', style: 'margin-top:16px' },
      h('label', { class: 'label', for: 'rs-pass' }, 'New password'), first),
    h('div', { class: 'field' },
      h('label', { class: 'label', for: 'rs-pass2' }, 'Repeat new password'), second),
    errorSlot,
    submit,
    h('p', { class: 'demo-hint' }, h('a', { href: '#/login' }, 'Back to sign-in')));

  root.append(h('div', { class: 'login' }, h('div', { class: 'login-wrap' },
    h('div', { class: 'login-hero' },
      h('p', { class: 'kicker' }, 'Disaster Commander Edge'),
      h('h1', null, 'Reset your ', h('span', null, 'password'))),
    token ? form : alertBox('error', 'This link has no reset token. Open the link from the email again.'))));
  return () => {};
}
