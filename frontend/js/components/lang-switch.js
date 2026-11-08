import { h } from '../dom.js';
import { go } from '../router.js';
import { t, getLocale, setLocale, SUPPORTED_LOCALES } from '../i18n/index.js';

// A language select. Choosing a language stores it, then re-runs the current route so every string on
// screen is drawn again in the new language. Returns the element; the caller places it.
export function langSwitch() {
  const select = h('select', {
    class: 'lang-switch__select',
    id: 'lang-switch',
    'aria-label': t('lang.label'),
  }, SUPPORTED_LOCALES.map((code) =>
    h('option', { value: code, selected: code === getLocale() }, t(`lang.${code}`))));

  select.addEventListener('change', () => {
    setLocale(select.value);
    go(window.location.hash || '#/');
  });

  return h('label', { class: 'lang-switch' },
    h('span', { class: 'lang-switch__label' }, t('lang.label')),
    select);
}
