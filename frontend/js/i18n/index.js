// Small i18n layer. Two languages (en, id). The chosen language code is the only thing stored, under one
// localStorage key. Nothing personal is stored here. Storage can be unavailable (private mode), so every
// access is wrapped and the app falls back to the browser language.

import en from './en.js';
import id from './id.js';

export const SUPPORTED_LOCALES = ['en', 'id'];
const STORAGE_KEY = 'dce.locale';
const DICTIONARIES = { en, id };
const listeners = new Set();

function isSupported(code) {
  return SUPPORTED_LOCALES.includes(code);
}

function readStored() {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isSupported(value) ? value : null;
  } catch {
    return null;
  }
}

function writeStored(code) {
  try {
    window.localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Storage unavailable: the choice lasts for this page load only.
  }
}

// Indonesian browsers get Bahasa Indonesia. Everything else gets English.
function detectBrowserLocale() {
  const lang = (typeof navigator !== 'undefined' && navigator.language) || '';
  return lang.toLowerCase().startsWith('id') ? 'id' : 'en';
}

let current = readStored() || detectBrowserLocale();

function applyDocumentLang() {
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.lang = current;
  }
}
applyDocumentLang();

export function getLocale() {
  return current;
}

export function setLocale(code) {
  if (!isSupported(code) || code === current) return current;
  current = code;
  writeStored(code);
  applyDocumentLang();
  listeners.forEach((fn) => {
    try {
      fn(current);
    } catch (err) {
      console.error('locale listener failed', err);
    }
  });
  return current;
}

// Returns an unsubscribe function.
export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Translate a key. {name} placeholders are replaced from vars. A key missing in the current language falls
// back to English, then to the key itself, so a missing string never shows as blank.
export function t(key, vars) {
  const dict = DICTIONARIES[current] || en;
  let text = dict[key];
  if (text === undefined) text = en[key];
  if (text === undefined) text = key;
  if (vars && typeof vars === 'object') {
    text = text.replace(/\{(\w+)\}/g, (match, name) =>
      Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match);
  }
  return text;
}
