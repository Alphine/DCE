// Shows a fixed banner while the browser sandbox is on. Loaded by index.html on every page.
import { h } from '../dom.js';
import { isSandbox, disableSandbox, resetSandbox } from './sandbox.js';

function mountBanner() {
  if (!isSandbox() || document.getElementById('sandbox-banner')) return;
  const resetBtn = h('button', { class: 'btn btn-sm', type: 'button', onclick: () => {
    resetSandbox();
    location.reload();
  } }, 'Reset sandbox data');
  const exitBtn = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => {
    disableSandbox();
    resetSandbox();
    location.hash = '#/login';
    location.reload();
  } }, 'Exit demo');
  const banner = h('div', { id: 'sandbox-banner', class: 'sandbox-banner', role: 'status' },
    h('strong', null, 'DEMO SANDBOX'),
    h('span', null, ' Sample data from a local review server. Changes stay in this browser only. Approvals here are simulated, and nothing reaches the production server.'),
    h('span', { class: 'sandbox-actions' }, resetBtn, exitBtn));
  document.body.prepend(banner);
}

window.addEventListener('dce:sandbox-on', mountBanner);
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountBanner);
else mountBanner();
