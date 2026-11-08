import { api } from '../api.js';
import { h, pageHead, spinner, emptyState, fmtDate, listOf } from '../dom.js';
import { langSwitch } from '../components/lang-switch.js';
import { parseHash } from '../router.js';
import { t, getLocale } from '../i18n/index.js';

// Public page: published warnings only, in the reader's language. No session is needed. The route is
// "#/public" and must be listed in PUBLIC_ROUTES in app.js. An optional "?country=XX" narrows the list.

function countryFromHash() {
  const raw = parseHash().query.get('country');
  return raw && /^[A-Za-z]{2}$/.test(raw) ? raw.toUpperCase() : null;
}

function warningCard(w) {
  const meta = [
    t('public.hazard', { hazard: t(`hazard.${w.hazard_type}`) }),
    t('public.area', { country: w.country_code }),
    t('public.published', { time: fmtDate(w.published_at) }),
  ].join(' · ');
  return h('article', { class: 'public-warning', lang: w.lang },
    h('h2', { class: 'public-warning__title' }, w.title),
    h('p', { class: 'public-warning__meta' }, meta),
    h('p', { class: 'public-warning__body' }, w.body));
}

export async function mount(root, ctx) {
  const { signal } = ctx;
  const country = countryFromHash();
  const list = h('div', { class: 'public-list', 'aria-live': 'polite' });

  root.append(h('div', { class: 'public-page' },
    pageHead(t('public.title'), t('public.subtitle')),
    h('div', { class: 'row' }, langSwitch()),
    list));

  function renderEmpty() {
    list.replaceChildren(emptyState(t('public.empty_title'), t('public.empty_detail')));
  }

  function renderError(message) {
    list.replaceChildren(h('div', { class: 'state-msg empty', role: 'alert' },
      h('strong', null, message),
      h('button', { class: 'btn btn-sm', type: 'button', onclick: load }, t('common.retry'))));
  }

  async function load() {
    list.replaceChildren(spinner(t('common.loading')));
    try {
      const data = await api.get('public/warnings', {
        query: { lang: getLocale(), country },
        signal,
        suppressAuthEvent: true,
      });
      if (signal.aborted) return;
      const items = listOf(data);
      if (items.length === 0) return renderEmpty();
      list.replaceChildren(...items.map(warningCard));
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      renderError(err.code === 'RATE_LIMITED' ? t('public.rate_limited') : t('public.load_failed'));
    }
  }

  await load();
}
