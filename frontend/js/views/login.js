import { api } from '../api.js';
import { h, alertBox } from '../dom.js';

// ctx: { signal, onLogin() } provided by app.js.
export async function mount(root, ctx) {
  const errorSlot = h('div', { hidden: true });
  const username = h('input', {
    id: 'login-user', name: 'username', type: 'text', autocomplete: 'username',
    required: true, spellcheck: 'false', autocapitalize: 'off',
  });
  const password = h('input', {
    id: 'login-pass', name: 'password', type: 'password', autocomplete: 'current-password', required: true,
  });
  const submit = h('button', { class: 'btn btn-primary btn-block btn-gate', type: 'submit' }, 'Enter command center');

  async function onSubmit(event) {
    event.preventDefault();
    errorSlot.hidden = true;
    errorSlot.replaceChildren();
    submit.disabled = true;
    submit.textContent = 'Signing in…';
    try {
      await api.post('auth/login', { username: username.value.trim(), password: password.value },
        { signal: ctx.signal, suppressAuthEvent: true });
      await ctx.onLogin();
    } catch (err) {
      if (ctx.signal.aborted) return;
      errorSlot.replaceChildren(alertBox('error', err.message));
      errorSlot.hidden = false;
      password.value = '';
      password.focus();
      submit.disabled = false;
      submit.textContent = 'Enter command center';
    }
  }

  // Forgot password: asks for the account email and always gives the same answer (no account check).
  const forgotEmail = h('input', { id: 'forgot-email', name: 'email', type: 'email', autocomplete: 'email',
    required: true, maxlength: '254', spellcheck: 'false', autocapitalize: 'off' });
  const forgotSlot = h('div', { 'aria-live': 'polite' });
  const forgotSubmit = h('button', { class: 'btn btn-block', type: 'submit' }, 'Send reset link');
  const forgotBox = h('form', { class: 'stack', hidden: true, novalidate: false, 'aria-label': 'Forgot password',
    onsubmit: async (event) => {
      event.preventDefault();
      forgotSlot.replaceChildren();
      forgotSubmit.disabled = true;
      try {
        const res = await api.post('auth/forgot', { email: forgotEmail.value.trim() },
          { signal: ctx.signal, suppressAuthEvent: true });
        forgotSlot.replaceChildren(h('p', { class: 'small' }, res && res.detail ? res.detail : 'If an account with that email exists, a reset link has been sent.'));
      } catch (err) {
        if (ctx.signal.aborted || err.name === 'AbortError') return;
        forgotSlot.replaceChildren(alertBox('error', err.message));
      } finally {
        forgotSubmit.disabled = false;
      }
    } },
    h('div', { class: 'field' },
      h('label', { class: 'label', for: 'forgot-email' }, 'Account email'),
      forgotEmail),
    forgotSlot,
    forgotSubmit);
  const forgotToggle = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', 'aria-expanded': 'false',
    onclick: () => {
      forgotBox.hidden = !forgotBox.hidden;
      forgotToggle.setAttribute('aria-expanded', String(!forgotBox.hidden));
      if (!forgotBox.hidden) forgotEmail.focus();
    } }, 'Forgot password?');

  const form = h('form', { class: 'login-card panel', novalidate: false, onsubmit: onSubmit, 'aria-labelledby': 'login-title' },
    h('h2', { id: 'login-title', class: 'panel-title' }, 'Operator sign-in'),
    h('p', { class: 'panel-sub' }, 'Sign in with your operator account to continue.'),
    h('div', { class: 'field', style: 'margin-top:16px' },
      h('label', { class: 'label', for: 'login-user' }, 'Username'),
      username),
    h('div', { class: 'field' },
      h('label', { class: 'label', for: 'login-pass' }, 'Password'),
      password),
    errorSlot,
    submit,
    h('div', { class: 'row', style: 'margin-top:10px' }, forgotToggle),
    forgotBox,
    h('p', { class: 'demo-hint' }, 'Use the seeded demo accounts: admin, analyst, reviewer, approver. Ask your operator for the password.'));

  root.append(h('div', { class: 'login' },
    h('div', { class: 'login-wrap' },
      h('div', { class: 'login-hero' },
        h('div', { class: 'radar', 'aria-hidden': 'true' }),
        h('p', { class: 'kicker' }, 'Disaster Commander Edge'),
        h('h1', null, 'Flood response, ', h('span', null, 'under command')),
        h('p', null, 'A sandboxed agent turns flood incident data into a situation report. Every result carries its data class. Every run passes a human gate. Every action lands in a hash-chained audit log.')),
      form)));

  submit.focus?.();
  return () => {};
}
