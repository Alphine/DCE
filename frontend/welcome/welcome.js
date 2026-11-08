/* Disaster Commander Edge landing page: English / Bahasa Indonesia switch.
 * Every element with data-i18n is set from DICT[lang][key]. English is the
 * default and is also the text shipped in index.html for no-JS readers. */
(function () {
  'use strict';

  var DICT = {
    en: {
      'meta.title': 'Disaster Commander Edge: disaster response, under command',
      'meta.description': 'Disaster Commander Edge: multi-hazard situational awareness with human-approved decisions. Offline-first, and built for use across countries.',
      'skip': 'Skip to content',
      'nav.what': 'What it does',
      'nav.trust': 'Trust',
      'nav.offline': 'Offline',
      'nav.global': 'Global',
      'nav.limits': 'Limits',
      'hero.eyebrow': 'Multi-hazard command edge',
      'hero.title': 'Disaster response, under command',
      'hero.lead': 'Multi-hazard situational awareness with human-approved decisions. Offline-first, and built to be used across countries.',
      'hero.ctaCommand': 'Open the command center',
      'hero.ctaPublic': 'Public warnings',
      'hero.tag1': 'Offline-first',
      'hero.tag2': 'Human-approved',
      'hero.tag3': 'Multi-country',
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
      'footer.leaflet': 'Map library: Leaflet (BSD 2-Clause)'
    },
    id: {
      'meta.title': 'Disaster Commander Edge: respons bencana, di bawah kendali',
      'meta.description': 'Disaster Commander Edge: kesadaran situasional multi-bahaya dengan keputusan yang disetujui manusia. Mengutamakan offline, dan dirancang untuk dipakai lintas negara.',
      'skip': 'Lewati ke konten',
      'nav.what': 'Fungsi',
      'nav.trust': 'Kepercayaan',
      'nav.offline': 'Offline',
      'nav.global': 'Global',
      'nav.limits': 'Batasan',
      'hero.eyebrow': 'Edge komando multi-bahaya',
      'hero.title': 'Respons bencana, di bawah kendali',
      'hero.lead': 'Kesadaran situasional multi-bahaya dengan keputusan yang disetujui manusia. Mengutamakan offline, dan dirancang untuk dipakai lintas negara.',
      'hero.ctaCommand': 'Buka pusat komando',
      'hero.ctaPublic': 'Peringatan publik',
      'hero.tag1': 'Mengutamakan offline',
      'hero.tag2': 'Disetujui manusia',
      'hero.tag3': 'Multi-negara',
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
      'footer.licence': 'Lisensi: akan ditetapkan oleh pemilik proyek',
      'footer.appTitle': 'Aplikasi',
      'footer.command': 'Pusat komando',
      'footer.public': 'Peringatan publik',
      'footer.about': 'Tentang dan arsitektur',
      'footer.dataTitle': 'Kredit',
      'footer.natural': 'Data peta: Natural Earth (domain publik)',
      'footer.leaflet': 'Pustaka peta: Leaflet (BSD 2-Clause)'
    }
  };

  var STORAGE_KEY = 'dce-welcome-lang';

  function readSaved() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function writeSaved(lang) {
    try {
      window.localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      /* Storage can be blocked; the switch still works for this visit. */
    }
  }

  function setMeta(selector, value) {
    var el = document.querySelector(selector);
    if (el) el.setAttribute('content', value);
  }

  function apply(lang) {
    var dict = DICT[lang] || DICT.en;
    document.documentElement.setAttribute('lang', lang);

    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      var key = nodes[i].getAttribute('data-i18n');
      if (Object.prototype.hasOwnProperty.call(dict, key)) {
        nodes[i].textContent = dict[key];
      }
    }

    document.title = dict['meta.title'];
    setMeta('meta[name="description"]', dict['meta.description']);
    setMeta('meta[property="og:title"]', dict['meta.title']);
    setMeta('meta[property="og:description"]', dict['meta.description']);

    var buttons = document.querySelectorAll('.lang-switch button[data-lang]');
    for (var j = 0; j < buttons.length; j++) {
      var active = buttons[j].getAttribute('data-lang') === lang;
      buttons[j].setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  }

  function initialLang() {
    var saved = readSaved();
    if (saved === 'en' || saved === 'id') return saved;
    var browser = (navigator.language || '').toLowerCase();
    return browser.indexOf('id') === 0 ? 'id' : 'en';
  }

  function init() {
    var current = initialLang();
    apply(current);

    var buttons = document.querySelectorAll('.lang-switch button[data-lang]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        var lang = event.currentTarget.getAttribute('data-lang');
        if (lang !== 'en' && lang !== 'id') return;
        current = lang;
        writeSaved(lang);
        apply(lang);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
