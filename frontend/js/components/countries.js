// Country choice for intake and proposals. ISO 3166-1 alpha-2 codes with English names. The list is short on
// purpose: the server validates the code against its own bundled list. The default is "not set" (empty).
import { h } from '../dom.js';

export const COUNTRIES = [
  ['AU', 'Australia'], ['BD', 'Bangladesh'], ['BR', 'Brazil'], ['CA', 'Canada'], ['CL', 'Chile'],
  ['CN', 'China'], ['CO', 'Colombia'], ['DE', 'Germany'], ['EG', 'Egypt'], ['ES', 'Spain'],
  ['ET', 'Ethiopia'], ['FR', 'France'], ['GB', 'United Kingdom'], ['GR', 'Greece'], ['ID', 'Indonesia'],
  ['IN', 'India'], ['IT', 'Italy'], ['JP', 'Japan'], ['KE', 'Kenya'], ['KH', 'Cambodia'],
  ['KR', 'South Korea'], ['LK', 'Sri Lanka'], ['MM', 'Myanmar'], ['MX', 'Mexico'], ['MY', 'Malaysia'],
  ['NG', 'Nigeria'], ['NP', 'Nepal'], ['NZ', 'New Zealand'], ['PE', 'Peru'], ['PH', 'Philippines'],
  ['PK', 'Pakistan'], ['PT', 'Portugal'], ['SG', 'Singapore'], ['TH', 'Thailand'], ['TR', 'Turkey'],
  ['TW', 'Taiwan'], ['US', 'United States'], ['VN', 'Vietnam'], ['ZA', 'South Africa'],
].map(([code, name]) => ({ code, name })).sort((a, b) => a.name.localeCompare(b.name));

const CODES = new Set(COUNTRIES.map((c) => c.code));

// A labelled country select. The caller reads field.select.value and sends countryOrNull(value).
export function countryField(id, label = 'Country (optional)') {
  const select = h('select', { id },
    h('option', { value: '' }, 'Not set'),
    COUNTRIES.map((c) => h('option', { value: c.code }, c.name)));
  const field = h('div', { class: 'field' }, h('label', { for: id }, label), select);
  return { field, select };
}

export function isKnownCountry(code) {
  return code === '' || CODES.has(code);
}

// Returns the value to send: an ISO code, or null when none was chosen.
export function countryOrNull(value) {
  return value && CODES.has(value) ? value : null;
}
