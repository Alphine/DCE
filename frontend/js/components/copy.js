import { h } from '../dom.js';
import { toast } from './toast.js';

export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the textarea method.
  }
  const ta = h('textarea', { style: { position: 'fixed', opacity: '0', pointerEvents: 'none' }, 'aria-hidden': 'true' });
  ta.value = text;
  document.body.append(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  ta.remove();
  return ok;
}

// Copy button. The label names what is copied, for screen readers.
export function copyButton(text, label = 'Copy') {
  const btn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': label, title: label }, 'Copy');
  btn.addEventListener('click', async () => {
    const ok = await copyText(String(text));
    toast(ok ? `${label}: copied.` : 'Copy failed. Select the text and copy it manually.', {
      kind: ok ? 'success' : 'error',
      timeout: 2500,
    });
  });
  return btn;
}
