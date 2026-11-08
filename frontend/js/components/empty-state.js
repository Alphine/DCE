// Empty state with an inline SVG icon, a title, a detail line and up to two in-app action links.
// Builds nodes only (createElement / createElementNS), never innerHTML. Server text goes in as text nodes.
// This module must not import dom.js (dom.js imports richEmpty from here), so h() is a minimal local copy.

const SVG_NS = 'http://www.w3.org/2000/svg';
const MAX_ACTIONS = 2;

// [tag, attributes] pairs drawn on a 24 x 24 grid. Same shapes as components/icons.js where they overlap.
const ICONS = {
  alerts: [
    ['path', { d: 'M6 16V11a6 6 0 0112 0v5l1.5 2h-15z' }],
    ['path', { d: 'M10 20a2 2 0 004 0' }],
  ],
  reports: [
    ['path', { d: 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z' }],
    ['path', { d: 'M14 3v6h6M8 13h8M8 17h5' }],
  ],
  datasets: [
    ['ellipse', { cx: 12, cy: 5, rx: 8, ry: 3 }],
    ['path', { d: 'M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5' }],
    ['path', { d: 'M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3' }],
  ],
  missions: [
    ['circle', { cx: 12, cy: 12, r: 9 }],
    ['circle', { cx: 12, cy: 12, r: 5 }],
    ['circle', { cx: 12, cy: 12, r: 1.5 }],
  ],
  logistics: [
    ['rect', { x: 2, y: 7, width: 12, height: 9, rx: 1 }],
    ['path', { d: 'M14 10h4l3 3v3h-7z' }],
    ['circle', { cx: 6, cy: 18, r: 1.8 }],
    ['circle', { cx: 17, cy: 18, r: 1.8 }],
  ],
  simulation: [
    ['polyline', { points: '3 12 7 6 11 18 15 9 19 14 21 12' }],
  ],
  none: [
    ['rect', { x: 3, y: 5, width: 18, height: 14, rx: 2 }],
    ['path', { d: 'M3 13h5l1 2h6l1-2h5' }],
  ],
};

function h(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props && typeof props === 'object') {
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = String(value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === 'object' ? child : document.createTextNode(String(child)));
  }
  return node;
}

function iconNamed(name) {
  return Object.prototype.hasOwnProperty.call(ICONS, name) ? name : 'none';
}

function svgIcon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  const attrs = {
    class: 'empty-icon',
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.6',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    focusable: 'false',
  };
  for (const [key, value] of Object.entries(attrs)) svg.setAttribute(key, value);
  for (const [tag, shape] of ICONS[iconNamed(name)]) {
    const part = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(shape)) part.setAttribute(key, String(value));
    svg.append(part);
  }
  return svg;
}

// Only in-app hash links are allowed, so an action can never be a javascript: or external URL.
function safeHref(href) {
  const value = String(href || '');
  return /^#\/[^\s"'<>]*$/.test(value) ? value : null;
}

function actionLinks(actions) {
  if (!Array.isArray(actions)) return [];
  return actions.slice(0, MAX_ACTIONS).reduce((links, action) => {
    const href = action ? safeHref(action.href) : null;
    if (action && action.label && href) links.push(h('a', { class: 'empty-action', href }, String(action.label)));
    return links;
  }, []);
}

export function richEmpty({ title, detail, icon, actions } = {}) {
  const links = actionLinks(actions);
  return h('div', { class: 'state-msg empty rich-empty', role: 'status' },
    svgIcon(icon),
    h('strong', { class: 'empty-title' }, title),
    detail ? h('span', { class: 'empty-detail' }, detail) : null,
    links.length ? h('div', { class: 'empty-actions' }, links) : null);
}
