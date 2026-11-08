// Public landing page. Shown at the app root (#/ or no hash) to visitors who are not signed in.
// Built with h() and svg() from dom.js. No innerHTML, no inline script, no data from the server.
// Text and the English / Bahasa Indonesia dictionary come from the former frontend/welcome/welcome.js.
// In-page links scroll with JavaScript so they never change the hash (the router reads the hash).
import { h, svg } from '../dom.js';

const DICT = {
  en: {
    'meta.title': 'Disaster Commander Edge: disaster response, under command',
    'meta.description': 'Disaster Commander Edge: multi-hazard situational awareness with human-approved decisions. Offline-first, and built for use across countries.',
    'top.signin': 'Sign in',
    'nav.label': 'Page sections',
    'nav.what': 'What it does',
    'nav.trust': 'Trust',
    'nav.offline': 'Offline',
    'nav.global': 'Global',
    'nav.limits': 'Limits',
    'lang.label': 'Language',
    'hero.eyebrow': 'Multi-hazard command edge',
    'hero.title': 'Disaster response, under command',
    'hero.lead': 'Multi-hazard situational awareness with human-approved decisions. Offline-first, and built to be used across countries.',
    'hero.ctaCommand': 'Open the command center',
    'hero.ctaPublic': 'Public warnings',
    'hero.ctaDemo': 'Try the demo: demo / demo',
    'hero.tagsLabel': 'Key properties',
    'hero.tag1': 'Offline-first',
    'hero.tag2': 'Human-approved',
    'hero.tag3': 'Multi-country',
    'art.title': 'Illustration of a situation radar',
    'art.desc': 'A radar display with a rotating sweep, hazard markers and a grid, illustrating live situational awareness. Decorative illustration, not a map of real data.',
    'what.eyebrow': 'Product',
    'what.title': 'What it does',
    'what.lead': 'One command view for the whole response cycle: what is happening, what it may lead to, what can be done, and who has agreed to do it.',
    'card1.title': 'Situation map',
    'card1.body': 'A Leaflet map with country outlines and switchable layers, so hazards, shelters, stock and teams sit on one picture.',
    'card2.title': 'Hazard intelligence',
    'card2.body': 'Rule packs for flood, tsunami, earthquake and wildfire. They are illustrative and hash-verified before use.',
    'card3.title': 'Simulation and planning',
    'card3.body': 'Reproducible what-if runs and per-district allocation. The same inputs always give the same outputs.',
    'card4.title': 'Logistics',
    'card4.body': 'Shelters, stock, teams and vehicles, with coverage gaps made visible so they can be closed.',
    'card5.title': 'Alerts and time series',
    'card5.body': 'Alerts and observed series over time, so trends show up before they become emergencies.',
    'card6.title': 'Reports with verification',
    'card6.body': 'Situation reports that carry their verification state, so readers can see what has been checked.',
    'card7.title': 'Missions with approval gate',
    'card7.body': 'A mission does not run until a person has approved it. The agent cannot start one on its own.',
    'card8.title': 'Public warnings',
    'card8.body': 'Warnings for the public in several languages, kept separate from the internal command view.',
    'trust.eyebrow': 'Trust',
    'trust.title': 'How trust is built',
    'trust.lead': 'Four rules keep the system honest about what it knows, what it guessed, and who decided.',
    'step1.title': 'Data is classed',
    'step1.body': 'Every value is an observation, verified, simulated or a decision. Simulated values are never shown as observations.',
    'step2.title': 'Two human gates',
    'step2.body': 'A plan and a mission each need an explicit human approval before they take effect.',
    'step3.title': 'Hash-chained audit log',
    'step3.body': 'Each action is written to an append-only log where every entry hashes the one before it. Altering history breaks the chain.',
    'step4.title': 'Sandboxed AI agent',
    'step4.body': 'The AI agent only plans. Deterministic engines do the computation, so results can be reproduced and checked.',
    'offline.eyebrow': 'Offline-first',
    'offline.title': 'Keeps working when the network does not',
    'offline.body': 'Install it as an app (PWA) on a phone or laptop. With the network off, it still works with data you have already seen.',
    'offline.body2': 'Actions you take wait in an outbox and are sent when the connection returns. A desktop build for Windows is published with the project releases.',
    'offline.item1': 'Installable as an app (PWA)',
    'offline.item2': 'Previously seen data is available with no network',
    'offline.item3': 'Actions go to an outbox and sync when online',
    'offline.item4': 'Windows desktop build from the project releases',
    'global.eyebrow': 'Global scope',
    'global.title': 'Usable across countries',
    'global.body': 'Hazards and response do not stop at borders. Every record carries its country, and every view can be filtered by country.',
    'global.item1': 'Country codes on every record',
    'global.item2': 'Country filter on the map and on lists',
    'global.item3': 'Rule packs declare the countries they cover',
    'limits.eyebrow': 'Read before use',
    'limits.title': 'Honest limits',
    'limits.item1a': 'Thresholds are illustrative.',
    'limits.item1b': 'Rule thresholds have not been validated against an authoritative standard.',
    'limits.item2a': 'Simulation is not observation.',
    'limits.item2b': 'Simulation outputs show what a model predicts. They are not records of what happened.',
    'limits.item3a': 'Not for operational use yet.',
    'limits.item3b': 'Do not use this product for real emergency decisions without validation for your own context.',
    'limits.about': 'Read the About page in the app',
    'footer.tagline': 'Disaster response, under command.',
    'footer.licence': 'Licence: MIT. See the LICENSE file in the repository.',
    'footer.appTitle': 'The app',
    'footer.command': 'Command center',
    'footer.public': 'Public warnings',
    'footer.about': 'About and architecture',
    'footer.dataTitle': 'Credits',
    'footer.natural': 'Map data: Natural Earth (public domain)',
    'footer.leaflet': 'Map library: Leaflet (BSD 2-Clause)',
  },
  id: {
    'meta.title': 'Disaster Commander Edge: respons bencana, di bawah kendali',
    'meta.description': 'Disaster Commander Edge: kesadaran situasional multi-bahaya dengan keputusan yang disetujui manusia. Mengutamakan offline, dan dirancang untuk dipakai lintas negara.',
    'top.signin': 'Masuk',
    'nav.label': 'Bagian halaman',
    'nav.what': 'Fungsi',
    'nav.trust': 'Kepercayaan',
    'nav.offline': 'Offline',
    'nav.global': 'Global',
    'nav.limits': 'Batasan',
    'lang.label': 'Bahasa',
    'hero.eyebrow': 'Edge komando multi-bahaya',
    'hero.title': 'Respons bencana, di bawah kendali',
    'hero.lead': 'Kesadaran situasional multi-bahaya dengan keputusan yang disetujui manusia. Mengutamakan offline, dan dirancang untuk dipakai lintas negara.',
    'hero.ctaCommand': 'Buka pusat komando',
    'hero.ctaPublic': 'Peringatan publik',
    'hero.ctaDemo': 'Coba demo: demo / demo',
    'hero.tagsLabel': 'Properti utama',
    'hero.tag1': 'Mengutamakan offline',
    'hero.tag2': 'Disetujui manusia',
    'hero.tag3': 'Multi-negara',
    'art.title': 'Ilustrasi radar situasi',
    'art.desc': 'Layar radar dengan sapuan berputar, penanda bahaya dan grid, sebagai ilustrasi kesadaran situasional. Ilustrasi dekoratif, bukan peta data nyata.',
    'what.eyebrow': 'Produk',
    'what.title': 'Fungsi utama',
    'what.lead': 'Satu tampilan komando untuk seluruh siklus respons: apa yang sedang terjadi, apa dampaknya, apa yang bisa dilakukan, dan siapa yang setuju melakukannya.',
    'card1.title': 'Peta situasi',
    'card1.body': 'Peta Leaflet dengan batas negara dan lapisan yang dapat dialihkan, sehingga bahaya, shelter, stok, dan tim tampak dalam satu gambar.',
    'card2.title': 'Intelijen bahaya',
    'card2.body': 'Paket aturan untuk banjir, tsunami, gempa, dan kebakaran hutan. Bersifat ilustratif dan diverifikasi hash sebelum dipakai.',
    'card3.title': 'Simulasi dan perencanaan',
    'card3.body': 'Skenario what-if yang dapat direproduksi dan alokasi per distrik. Input yang sama selalu menghasilkan output yang sama.',
    'card4.title': 'Logistik',
    'card4.body': 'Shelter, stok, tim, dan kendaraan, dengan celah cakupan yang dibuat terlihat agar bisa ditutup.',
    'card5.title': 'Peringatan dan deret waktu',
    'card5.body': 'Peringatan dan data observasi dari waktu ke waktu, sehingga tren terlihat sebelum menjadi darurat.',
    'card6.title': 'Laporan dengan verifikasi',
    'card6.body': 'Laporan situasi yang memuat status verifikasinya, sehingga pembaca tahu apa yang sudah diperiksa.',
    'card7.title': 'Misi dengan gerbang persetujuan',
    'card7.body': 'Misi tidak berjalan sebelum disetujui manusia. Agen AI tidak dapat memulai misi sendiri.',
    'card8.title': 'Peringatan publik',
    'card8.body': 'Peringatan untuk masyarakat dalam beberapa bahasa, dipisahkan dari tampilan komando internal.',
    'trust.eyebrow': 'Kepercayaan',
    'trust.title': 'Bagaimana kepercayaan dibangun',
    'trust.lead': 'Empat aturan menjaga sistem tetap jujur tentang apa yang diketahui, apa yang diperkirakan, dan siapa yang memutuskan.',
    'step1.title': 'Data diklasifikasikan',
    'step1.body': 'Setiap nilai adalah observasi, terverifikasi, simulasi, atau keputusan. Nilai simulasi tidak pernah ditampilkan sebagai observasi.',
    'step2.title': 'Dua gerbang manusia',
    'step2.body': 'Rencana dan misi masing-masing memerlukan persetujuan manusia yang eksplisit sebelum berlaku.',
    'step3.title': 'Log audit berantai hash',
    'step3.body': 'Setiap tindakan ditulis ke log yang hanya bisa ditambah, dan setiap entri memuat hash entri sebelumnya. Mengubah riwayat akan memutus rantai.',
    'step4.title': 'Agen AI dalam sandbox',
    'step4.body': 'Agen AI hanya merencanakan. Mesin deterministik yang menghitung, sehingga hasilnya dapat direproduksi dan diperiksa.',
    'offline.eyebrow': 'Mengutamakan offline',
    'offline.title': 'Tetap bekerja saat jaringan tidak ada',
    'offline.body': 'Pasang sebagai aplikasi (PWA) di ponsel atau laptop. Saat jaringan mati, aplikasi tetap bekerja dengan data yang sudah pernah dilihat.',
    'offline.body2': 'Tindakan yang Anda lakukan menunggu di outbox dan dikirim saat koneksi kembali. Build desktop untuk Windows tersedia di rilis proyek.',
    'offline.item1': 'Dapat dipasang sebagai aplikasi (PWA)',
    'offline.item2': 'Data yang pernah dilihat tersedia tanpa jaringan',
    'offline.item3': 'Tindakan masuk ke outbox dan disinkronkan saat online',
    'offline.item4': 'Build desktop Windows dari rilis proyek',
    'global.eyebrow': 'Cakupan global',
    'global.title': 'Dapat dipakai lintas negara',
    'global.body': 'Bahaya dan respons tidak berhenti di perbatasan. Setiap catatan membawa kode negaranya, dan setiap tampilan dapat difilter per negara.',
    'global.item1': 'Kode negara pada setiap catatan',
    'global.item2': 'Filter negara pada peta dan daftar',
    'global.item3': 'Paket aturan menyatakan negara yang dicakupnya',
    'limits.eyebrow': 'Baca sebelum digunakan',
    'limits.title': 'Batasan yang jujur',
    'limits.item1a': 'Ambang batas bersifat ilustratif.',
    'limits.item1b': 'Ambang batas aturan belum divalidasi terhadap standar otoritatif.',
    'limits.item2a': 'Simulasi bukan observasi.',
    'limits.item2b': 'Output simulasi menunjukkan prediksi model. Itu bukan catatan tentang apa yang benar-benar terjadi.',
    'limits.item3a': 'Belum untuk penggunaan operasional.',
    'limits.item3b': 'Jangan gunakan produk ini untuk keputusan darurat nyata tanpa validasi untuk konteks Anda.',
    'limits.about': 'Baca halaman Tentang di aplikasi',
    'footer.tagline': 'Respons bencana, di bawah kendali.',
    'footer.licence': 'Lisensi: MIT. Lihat berkas LICENSE di repositori.',
    'footer.appTitle': 'Aplikasi',
    'footer.command': 'Pusat komando',
    'footer.public': 'Peringatan publik',
    'footer.about': 'Tentang dan arsitektur',
    'footer.dataTitle': 'Kredit',
    'footer.natural': 'Data peta: Natural Earth (domain publik)',
    'footer.leaflet': 'Pustaka peta: Leaflet (BSD 2-Clause)',
  },
};

// Same storage key as the former welcome page, so a language choice carries over.
const STORAGE_KEY = 'dce-welcome-lang';

// Each card: icon shapes (see ICONS), title key, body key.
const CARDS = [
  { icon: 1, title: 'card1.title', body: 'card1.body' },
  { icon: 2, title: 'card2.title', body: 'card2.body' },
  { icon: 3, title: 'card3.title', body: 'card3.body' },
  { icon: 4, title: 'card4.title', body: 'card4.body' },
  { icon: 5, title: 'card5.title', body: 'card5.body' },
  { icon: 6, title: 'card6.title', body: 'card6.body' },
  { icon: 7, title: 'card7.title', body: 'card7.body' },
  { icon: 8, title: 'card8.title', body: 'card8.body' },
];

const ICONS = {
  1: [['path', { d: 'M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z' }], ['path', { d: 'M9 4v14M15 6v14' }]],
  2: [['path', { d: 'M4 19V5M4 19h16' }], ['path', { d: 'M8 15l4-5 3 3 5-7' }]],
  3: [['circle', { cx: '12', cy: '12', r: '8' }], ['path', { d: 'M12 8v4l3 2' }]],
  4: [['rect', { x: '3', y: '7', width: '18', height: '12', rx: '2' }], ['path', { d: 'M8 7V5h8v2M3 12h18' }]],
  5: [['path', { d: 'M3 12h4l3-7 4 14 3-7h4' }]],
  6: [['path', { d: 'M7 3h8l4 4v14H7z' }], ['path', { d: 'M15 3v4h4M10 12l2 2 4-4' }]],
  7: [['path', { d: 'M5 3v18M5 4h11l-2 4 2 4H5' }]],
  8: [['path', { d: 'M4 11v2a1 1 0 001 1h2l5 4V6L7 10H5a1 1 0 00-1 1z' }], ['path', { d: 'M16 9a4 4 0 010 6' }]],
};

const SECTION_LINKS = ['what', 'trust', 'offline', 'global', 'limits'];

function readSaved() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeSaved(lang) {
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Storage can be blocked; the switch still works for this visit.
  }
}

function initialLang() {
  const saved = readSaved();
  if (saved === 'en' || saved === 'id') return saved;
  const browser = (navigator.language || '').toLowerCase();
  return browser.indexOf('id') === 0 ? 'id' : 'en';
}

function metaContent(selector) {
  const el = document.querySelector(selector);
  return el ? el.getAttribute('content') : null;
}

function setMeta(selector, value) {
  const el = document.querySelector(selector);
  if (el && value !== null) el.setAttribute('content', value);
}

// Scrolls to a section without changing the hash, so the router is not involved.
function jump(id) {
  return (event) => {
    const target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  };
}

function brandMark() {
  return svg('svg', { viewBox: '0 0 32 32', 'aria-hidden': 'true', focusable: 'false' },
    svg('rect', { width: '32', height: '32', rx: '7', fill: '#101728', stroke: '#ffb020', 'stroke-width': '1.5' }),
    svg('circle', { cx: '16', cy: '16', r: '9', fill: 'none', stroke: '#3fd8f0', 'stroke-width': '1.5' }),
    svg('circle', { cx: '16', cy: '16', r: '3', fill: '#ffb020' }));
}

function cardIcon(n) {
  return svg('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'aria-hidden': 'true', focusable: 'false' },
    ICONS[n].map(([tag, attrs]) => svg(tag, attrs)));
}

function radar(t) {
  return svg('svg', { viewBox: '0 0 480 480', role: 'img', 'aria-labelledby': 'landing-art-title landing-art-desc' },
    svg('title', { id: 'landing-art-title' }, t('art.title')),
    svg('desc', { id: 'landing-art-desc' }, t('art.desc')),
    svg('defs', null,
      svg('radialGradient', { id: 'landing-glow', cx: '50%', cy: '50%', r: '50%' },
        svg('stop', { offset: '0%', 'stop-color': '#ffb020', 'stop-opacity': '0.35' }),
        svg('stop', { offset: '100%', 'stop-color': '#ffb020', 'stop-opacity': '0' })),
      svg('linearGradient', { id: 'landing-beam', x1: '0', y1: '0', x2: '1', y2: '0' },
        svg('stop', { offset: '0%', 'stop-color': '#3fd8f0', 'stop-opacity': '0' }),
        svg('stop', { offset: '100%', 'stop-color': '#3fd8f0', 'stop-opacity': '0.45' }))),
    svg('rect', { width: '480', height: '480', rx: '12', fill: '#05070d' }),
    svg('g', { stroke: '#a0b4dc', 'stroke-opacity': '0.14', 'stroke-width': '1' },
      svg('path', { d: 'M0 80H480M0 160H480M0 240H480M0 320H480M0 400H480M80 0V480M160 0V480M240 0V480M320 0V480M400 0V480' })),
    svg('circle', { cx: '240', cy: '240', r: '60', fill: 'url(#landing-glow)' }),
    svg('g', { fill: 'none', stroke: '#3fd8f0', 'stroke-opacity': '0.4', 'stroke-width': '1.2' },
      svg('circle', { cx: '240', cy: '240', r: '60' }),
      svg('circle', { cx: '240', cy: '240', r: '120' }),
      svg('circle', { cx: '240', cy: '240', r: '180' })),
    svg('g', { class: 'sweep' },
      svg('path', { d: 'M240 240 L240 60 A180 180 0 0 1 395 150 Z', fill: 'url(#landing-beam)' }),
      svg('line', { x1: '240', y1: '240', x2: '240', y2: '60', stroke: '#3fd8f0', 'stroke-width': '1.5' })),
    svg('circle', { cx: '240', cy: '240', r: '6', fill: '#ffb020' }),
    svg('g', { class: 'blink' },
      svg('circle', { cx: '330', cy: '170', r: '7', fill: '#ff4d62' }),
      svg('circle', { cx: '150', cy: '300', r: '6', fill: '#ffb020' }),
      svg('circle', { cx: '300', cy: '330', r: '5', fill: '#3ee39a' })),
    svg('g', { 'font-family': 'JetBrains Mono, monospace', 'font-size': '13', fill: '#8f9bb8' },
      svg('text', { x: '16', y: '28' }, 'GRID 1 KM'),
      svg('text', { x: '330', y: '28' }, 'ANALYST MODE')));
}

function langSwitch(lang, t, pick) {
  return h('div', { class: 'lang-switch', role: 'group', 'aria-label': t('lang.label') },
    ['en', 'id'].map((code) => h('button', {
      type: 'button',
      'data-lang': code,
      'aria-pressed': code === lang ? 'true' : 'false',
      lang: code,
      onclick: () => pick(code),
    }, code.toUpperCase())));
}

function topBar(lang, t, pick) {
  return h('header', { class: 'site-header' },
    h('div', { class: 'wrap' },
      h('a', { class: 'brand', href: '#landing-top', 'aria-label': 'Disaster Commander Edge, top of page', onclick: jump('landing-top') },
        brandMark(),
        h('span', null, 'Disaster Commander Edge')),
      h('nav', { class: 'nav-links', 'aria-label': t('nav.label') },
        SECTION_LINKS.map((id) => h('a', { href: `#landing-${id}`, onclick: jump(`landing-${id}`) }, t(`nav.${id}`)))),
      h('div', { class: 'top-actions' },
        langSwitch(lang, t, pick),
        h('a', { class: 'btn btn-sm', href: '#/login' }, t('top.signin')))));
}

function hero(t) {
  return h('section', { class: 'hero', id: 'landing-top', 'aria-labelledby': 'landing-hero-title' },
    h('div', { class: 'wrap hero-grid' },
      h('div', null,
        h('p', { class: 'eyebrow' }, t('hero.eyebrow')),
        h('h1', { id: 'landing-hero-title' }, t('hero.title')),
        h('p', { class: 'lead' }, t('hero.lead')),
        h('div', { class: 'hero-actions' },
          h('a', { class: 'btn btn-primary', href: '#/login' }, t('hero.ctaCommand')),
          h('a', { class: 'btn', href: '#/public' }, t('hero.ctaPublic')),
          h('a', { class: 'btn btn-demo', href: '#/login' }, t('hero.ctaDemo'))),
        h('ul', { class: 'tags', 'aria-label': t('hero.tagsLabel') },
          h('li', null, t('hero.tag1')),
          h('li', null, t('hero.tag2')),
          h('li', null, t('hero.tag3')))),
      h('figure', { class: 'hero-art' }, radar(t))));
}

function whatSection(t) {
  return h('section', { class: 'section', id: 'landing-what', 'aria-labelledby': 'landing-what-title' },
    h('div', { class: 'wrap' },
      h('div', { class: 'section-head' },
        h('p', { class: 'eyebrow' }, t('what.eyebrow')),
        h('h2', { id: 'landing-what-title' }, t('what.title')),
        h('p', null, t('what.lead'))),
      h('ul', { class: 'cards' },
        CARDS.map((card) => h('li', { class: 'card' },
          h('span', { class: 'card-icon', 'aria-hidden': 'true' }, cardIcon(card.icon)),
          h('h3', null, t(card.title)),
          h('p', null, t(card.body)))))));
}

function trustSection(t) {
  return h('section', { class: 'section', id: 'landing-trust', 'aria-labelledby': 'landing-trust-title' },
    h('div', { class: 'wrap' },
      h('div', { class: 'section-head' },
        h('p', { class: 'eyebrow' }, t('trust.eyebrow')),
        h('h2', { id: 'landing-trust-title' }, t('trust.title')),
        h('p', null, t('trust.lead'))),
      h('ol', { class: 'steps' },
        [1, 2, 3, 4].map((n) => h('li', null,
          h('h3', null, t(`step${n}.title`)),
          h('p', null, t(`step${n}.body`)))))));
}

function offlineSection(t) {
  return h('section', { class: 'section', id: 'landing-offline', 'aria-labelledby': 'landing-offline-title' },
    h('div', { class: 'wrap split' },
      h('div', null,
        h('p', { class: 'eyebrow' }, t('offline.eyebrow')),
        h('h2', { id: 'landing-offline-title' }, t('offline.title')),
        h('p', { class: 'body' }, t('offline.body')),
        h('p', { class: 'body' }, t('offline.body2'))),
      h('ul', { class: 'checklist' },
        [1, 2, 3, 4].map((n) => h('li', null, t(`offline.item${n}`))))));
}

function globalSection(t) {
  return h('section', { class: 'section', id: 'landing-global', 'aria-labelledby': 'landing-global-title' },
    h('div', { class: 'wrap split' },
      h('div', null,
        h('p', { class: 'eyebrow' }, t('global.eyebrow')),
        h('h2', { id: 'landing-global-title' }, t('global.title')),
        h('p', { class: 'body' }, t('global.body'))),
      h('ul', { class: 'checklist' },
        [1, 2, 3].map((n) => h('li', null, t(`global.item${n}`))))));
}

function limitsSection(t) {
  return h('section', { class: 'section', id: 'landing-limits', 'aria-labelledby': 'landing-limits-title' },
    h('div', { class: 'wrap' },
      h('div', { class: 'limits' },
        h('p', { class: 'eyebrow' }, t('limits.eyebrow')),
        h('h2', { id: 'landing-limits-title' }, t('limits.title')),
        h('ul', null,
          h('li', null, h('strong', null, t('limits.item1a')), ' ', h('span', null, t('limits.item1b'))),
          h('li', null, h('strong', null, t('limits.item2a')), ' ', h('span', null, t('limits.item2b'))),
          h('li', null, h('strong', null, t('limits.item3a')), ' ', h('span', null, t('limits.item3b')))),
        h('p', { class: 'more' }, h('a', { href: '#/about' }, t('limits.about'))))));
}

function footer(t) {
  return h('footer', { class: 'site-footer' },
    h('div', { class: 'wrap footer-grid' },
      h('div', null,
        h('a', { class: 'brand', href: '#landing-top', onclick: jump('landing-top') },
          brandMark(),
          h('span', null, 'Disaster Commander Edge')),
        h('p', null, t('footer.tagline')),
        h('p', null, t('footer.licence'))),
      h('nav', { 'aria-labelledby': 'landing-footer-app' },
        h('h2', { id: 'landing-footer-app' }, t('footer.appTitle')),
        h('ul', null,
          h('li', null, h('a', { href: '#/login' }, t('footer.command'))),
          h('li', null, h('a', { href: '#/public' }, t('footer.public'))),
          h('li', null, h('a', { href: '#/about' }, t('footer.about'))))),
      h('div', null,
        h('h2', null, t('footer.dataTitle')),
        h('ul', null,
          h('li', null, t('footer.natural')),
          h('li', null, t('footer.leaflet'))))));
}

function page(t, lang, pick) {
  return h('div', { class: 'landing' },
    topBar(lang, t, pick),
    h('div', { class: 'landing-main' },
      hero(t),
      whatSection(t),
      trustSection(t),
      offlineSection(t),
      globalSection(t),
      limitsSection(t)),
    footer(t));
}

// Renders into the app's view. The returned cleanup restores the document language and description.
export async function mount(root) {
  const previousLang = document.documentElement.getAttribute('lang');
  const previousDescription = metaContent('meta[name="description"]');
  let lang = initialLang();
  const host = h('div', { class: 'landing-host' });
  root.append(host);

  function render(focusCode) {
    const t = (key) => (DICT[lang] && DICT[lang][key] !== undefined ? DICT[lang][key] : DICT.en[key]);
    document.documentElement.setAttribute('lang', lang);
    document.title = t('meta.title');
    setMeta('meta[name="description"]', t('meta.description'));
    host.replaceChildren(page(t, lang, (code) => {
      if (code !== 'en' && code !== 'id') return;
      lang = code;
      writeSaved(code);
      render(code);
    }));
    if (focusCode) {
      const button = host.querySelector(`.lang-switch button[data-lang="${focusCode}"]`);
      if (button) button.focus({ preventScroll: true });
    }
  }

  render(null);

  return () => {
    document.documentElement.setAttribute('lang', previousLang || 'en');
    setMeta('meta[name="description"]', previousDescription);
  };
}
