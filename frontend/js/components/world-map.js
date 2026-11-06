// Interactive world map: country outlines (assets/world-map.svg, inlined) with two point layers.
// Disasters are amber circles; logistics are cyan diamonds. Colour is never the only cue.
// Keyboard: the map is one listbox. Arrow keys or Home/End move between visible points, Enter or Space
// selects, Escape clears the selection, + and - zoom, 0 resets the view. Tab leaves the map.
// Mouse and touch: wheel or pinch zooms at the pointer, drag pans, click selects.
// Nothing here runs inline script or inline event attributes (CSP).
import { h } from '../dom.js';
import { project, isInWorldView, WORLD_VIEWBOX } from './geo.js';

export const LAYERS = Object.freeze({
  disaster: Object.freeze({ id: 'disaster', label: 'Disaster incidents', shape: 'circle', color: '#ffb020' }),
  logistics: Object.freeze({ id: 'logistics', label: 'Logistics sites', shape: 'diamond', color: '#3fd8f0' }),
});

const SVG_NS = 'http://www.w3.org/2000/svg';
const W = WORLD_VIEWBOX.width;
const H = WORLD_VIEWBOX.height;
const MIN_SCALE = 1;
const MAX_SCALE = 12;
const DRAG_SLOP_PX = 5;
const reduceMotionQuery = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;

function svgEl(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children) if (child) el.append(child);
  return el;
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function formatCoords(lat, lon) {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(4)} ${ns}, ${Math.abs(lon).toFixed(4)} ${ew}`;
}

// Shared by the map tooltip and the detail card in the view.
export function pointDescription(p) {
  const layer = LAYERS[p.layer] || LAYERS.disaster;
  return { layerLabel: layer.label, coords: formatCoords(p.lat, p.lon) };
}

// Outline paths are fetched once per page load and reused by every map instance.
let outlinePromise = null;
function loadOutline() {
  if (!outlinePromise) {
    const url = new URL('../../assets/world-map.svg', import.meta.url);
    outlinePromise = fetch(url, { credentials: 'same-origin' })
      .then((res) => {
        if (!res.ok) throw new Error(`World map outline returned HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => {
        const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
        if (doc.querySelector('parsererror')) throw new Error('World map outline is not valid SVG');
        return [...doc.querySelectorAll('g.world-countries > path')];
      })
      .catch((err) => {
        outlinePromise = null;
        throw err;
      });
  }
  return outlinePromise;
}

// points: [{ label, lat, lon, layer: 'disaster' | 'logistics', type?, details?: [{label, value}] }]
// layers: { disaster: boolean, logistics: boolean } initial visibility.
// onSelect(point | null, index) is called on user selection (not on programmatic select()).
export function createWorldMap(container, { points = [], layers = {}, onSelect } = {}) {
  const visible = { disaster: layers.disaster !== false, logistics: layers.logistics !== false };
  const state = { scale: 1, tx: 0, ty: 0, active: -1, selected: -1 };
  const controller = new AbortController();
  const signal = controller.signal;
  let destroyed = false;
  let rafId = 0;
  let resizeObserver = null;
  const pointers = new Map();
  let drag = null; // { startX, startY, lastX, lastY, moved }
  let pinchStart = null; // { distance, scale }
  let suppressClick = false;

  const skipped = [];
  const items = [];

  const svg = svgEl('svg', {
    class: 'wm-svg', viewBox: `0 0 ${W} ${H}`, role: 'presentation', focusable: 'false', preserveAspectRatio: 'xMidYMid meet',
  });
  const viewport = svgEl('g', { class: 'wm-viewport' });
  const countryLayer = svgEl('g', { class: 'wm-countries', 'aria-hidden': 'true' });
  const markerLayer = svgEl('g', { class: 'wm-markers' });
  viewport.append(countryLayer, markerLayer);
  svg.append(viewport);

  const stage = h('div', {
    class: 'wm-stage',
    role: 'listbox',
    tabindex: '0',
    'aria-label': 'Map points. Use arrow keys to move between points, Enter to select, Escape to clear, plus and minus to zoom.',
    'aria-multiselectable': 'false',
  }, svg);
  const tooltip = h('div', { class: 'wm-tooltip', role: 'tooltip', hidden: true });
  const zoomIn = h('button', { class: 'btn btn-sm btn-ghost wm-btn', type: 'button', 'aria-label': 'Zoom in', title: 'Zoom in (+)' }, '+');
  const zoomOut = h('button', { class: 'btn btn-sm btn-ghost wm-btn', type: 'button', 'aria-label': 'Zoom out', title: 'Zoom out (-)' }, '−');
  const resetBtn = h('button', { class: 'btn btn-sm btn-ghost wm-btn wm-btn--text', type: 'button', 'aria-label': 'Reset view', title: 'Reset view (0)' }, 'Reset');
  const controls = h('div', { class: 'wm-controls' }, zoomIn, zoomOut, resetBtn);
  const root = h('div', { class: 'wm', 'data-testid': 'world-map' }, stage, tooltip, controls);
  container.replaceChildren(root);

  // Markers
  points.forEach((p, index) => {
    const layerDef = LAYERS[p.layer] || LAYERS.disaster;
    const pos = project(p.lat, p.lon);
    if (!pos || !isInWorldView(pos, 12)) {
      skipped.push(p.label);
      return;
    }
    const shape = layerDef.shape === 'diamond'
      ? svgEl('path', { class: 'wm-shape', d: 'M0,-6.5 L6.5,0 L0,6.5 L-6.5,0 Z' })
      : svgEl('circle', { class: 'wm-shape', r: 5.5 });
    const ring = svgEl('circle', { class: 'wm-ring', r: 10, fill: 'none' });
    const hit = svgEl('circle', { class: 'wm-hit', r: 11, fill: 'transparent' });
    const g = svgEl('g', {
      class: `wm-marker wm-marker--${layerDef.id}`,
      id: `wm-pt-${index}`,
      role: 'option',
      'aria-selected': 'false',
      'data-index': index,
      'data-layer': layerDef.id,
    }, hit, ring, shape);
    markerLayer.append(g);
    items.push({ index, point: p, pos, g, layer: layerDef.id });
  });

  const counts = { disaster: 0, logistics: 0 };
  for (const item of items) counts[item.layer] += 1;
  const labelFor = (item) => {
    const d = pointDescription(item.point);
    const type = item.point.type ? `, ${item.point.type}` : '';
    return `${item.point.label}, ${d.layerLabel}${type}, ${d.coords}`;
  };
  for (const item of items) item.g.setAttribute('aria-label', labelFor(item));

  function applyLayerVisibility() {
    for (const item of items) item.g.style.display = visible[item.layer] ? '' : 'none';
    if (state.active >= 0 && !isVisibleIndex(state.active)) setActive(-1, false);
  }

  function isVisibleIndex(index) {
    const item = items.find((it) => it.index === index);
    return !!item && visible[item.layer];
  }

  function visibleItems() {
    return items.filter((it) => visible[it.layer]);
  }

  // Screen size of 1 SVG unit (CSS px per unit is 1 / unitsPerPx).
  function unitsPerPx() {
    const m = svg.getScreenCTM();
    return m && m.a ? 1 / m.a : 0.4;
  }

  function toSvg(clientX, clientY) {
    const m = svg.getScreenCTM();
    if (!m) return { x: W / 2, y: H / 2 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    return pt.matrixTransform(m.inverse());
  }

  function clampView(v) {
    v.scale = clamp(v.scale, MIN_SCALE, MAX_SCALE);
    v.tx = clamp(v.tx, W * (1 - v.scale), 0);
    v.ty = clamp(v.ty, H * (1 - v.scale), 0);
    return v;
  }

  function paint() {
    viewport.setAttribute('transform', `translate(${state.tx.toFixed(2)} ${state.ty.toFixed(2)}) scale(${state.scale.toFixed(4)})`);
    const upp = unitsPerPx();
    const m = upp / state.scale; // marker group scale: keeps markers a constant size on screen
    for (const item of items) {
      item.g.setAttribute('transform', `translate(${item.pos.x.toFixed(2)} ${item.pos.y.toFixed(2)}) scale(${m.toFixed(5)})`);
    }
    markerLayer.setAttribute('data-scale', state.scale.toFixed(2));
    if (state.active >= 0) positionTooltip();
  }

  function stopAnimation() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  function animateTo(target, duration = 260) {
    stopAnimation();
    const from = { scale: state.scale, tx: state.tx, ty: state.ty };
    const to = clampView({ ...target });
    if (duration <= 0 || reduceMotionQuery?.matches) {
      Object.assign(state, to);
      paint();
      return;
    }
    const t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      const e = 1 - (1 - t) ** 3;
      state.scale = from.scale + (to.scale - from.scale) * e;
      state.tx = from.tx + (to.tx - from.tx) * e;
      state.ty = from.ty + (to.ty - from.ty) * e;
      paint();
      rafId = t < 1 ? requestAnimationFrame(step) : 0;
    };
    rafId = requestAnimationFrame(step);
  }

  function zoomAt(newScale, cx, cy, duration = 0) {
    const wx = (cx - state.tx) / state.scale;
    const wy = (cy - state.ty) / state.scale;
    animateTo({ scale: newScale, tx: cx - wx * newScale, ty: cy - wy * newScale }, duration);
  }

  function zoomCentre(factor, duration = 200) {
    const cx = W / 2;
    const cy = H / 2;
    zoomAt(clamp(state.scale * factor, MIN_SCALE, MAX_SCALE), cx, cy, duration);
  }

  function centreOn(item, duration = 260) {
    if (state.scale <= 1) return;
    animateTo({ scale: state.scale, tx: W / 2 - item.pos.x * state.scale, ty: H / 2 - item.pos.y * state.scale }, duration);
  }

  function fit(duration = 260) {
    const list = visibleItems();
    if (!list.length) return resetView(duration);
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
    for (const it of list) {
      x0 = Math.min(x0, it.pos.x); y0 = Math.min(y0, it.pos.y);
      x1 = Math.max(x1, it.pos.x); y1 = Math.max(y1, it.pos.y);
    }
    const pad = 160;
    const bw = Math.max(x1 - x0 + pad * 2, 260);
    const bh = Math.max(y1 - y0 + pad * 2, 200);
    const scale = clamp(Math.min(W / bw, H / bh), MIN_SCALE, MAX_SCALE);
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    animateTo({ scale, tx: W / 2 - cx * scale, ty: H / 2 - cy * scale }, duration);
  }

  function resetView(duration = 260) {
    animateTo({ scale: 1, tx: 0, ty: 0 }, duration);
  }

  function describeTooltip(item) {
    const p = item.point;
    const d = pointDescription(p);
    const lines = (p.details || []).slice(0, 6).map((line) =>
      h('span', { class: 'wm-tip-line' }, `${line.label}: ${line.value}`));
    return [
      h('strong', { class: 'wm-tip-title' }, p.label),
      h('span', { class: 'wm-tip-type' }, `${d.layerLabel}${p.type ? ` · ${p.type}` : ''}`),
      ...lines,
      h('span', { class: 'wm-tip-coords mono' }, d.coords),
    ];
  }

  function showTooltip(item) {
    tooltip.replaceChildren(...describeTooltip(item));
    tooltip.hidden = false;
    tooltip.dataset.index = String(item.index);
    positionTooltip();
  }

  function hideTooltip() {
    tooltip.hidden = true;
    tooltip.replaceChildren();
  }

  function positionTooltip() {
    if (tooltip.hidden) return;
    const item = items.find((it) => String(it.index) === tooltip.dataset.index);
    if (!item || !visible[item.layer]) return hideTooltip();
    const box = stage.getBoundingClientRect();
    const r = item.g.getBoundingClientRect();
    const anchorX = r.left + r.width / 2 - box.left;
    const anchorY = r.top - box.top;
    const width = tooltip.offsetWidth || 220;
    const height = tooltip.offsetHeight || 80;
    const left = clamp(anchorX - width / 2, 6, Math.max(6, box.width - width - 6));
    const top = anchorY - height - 12 < 6 ? r.bottom - box.top + 12 : anchorY - height - 12;
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
  }

  // Selection and the active (keyboard focus) point are separate states. Both are shown with classes.
  function setActive(index, scroll = true) {
    const prev = items.find((it) => it.index === state.active);
    if (prev) prev.g.classList.remove('is-active');
    state.active = index;
    stage.removeAttribute('aria-activedescendant');
    if (index < 0) {
      hideTooltip();
      return;
    }
    const item = items.find((it) => it.index === index);
    if (!item) return;
    item.g.classList.add('is-active');
    stage.setAttribute('aria-activedescendant', item.g.id);
    showTooltip(item);
    if (scroll) centreOn(item);
  }

  function setSelected(index, notify) {
    const prev = items.find((it) => it.index === state.selected);
    if (prev) {
      prev.g.classList.remove('is-selected');
      prev.g.setAttribute('aria-selected', 'false');
    }
    state.selected = index;
    const item = items.find((it) => it.index === index);
    if (item) {
      item.g.classList.add('is-selected');
      item.g.setAttribute('aria-selected', 'true');
    }
    if (notify && typeof onSelect === 'function') onSelect(item ? item.point : null, index);
  }

  function nearestVisible(delta) {
    const list = visibleItems();
    if (!list.length) return -1;
    const at = list.findIndex((it) => it.index === state.active);
    const next = at < 0 ? (delta > 0 ? 0 : list.length - 1) : clamp(at + delta, 0, list.length - 1);
    return list[next].index;
  }

  // Keyboard
  stage.addEventListener('keydown', (e) => {
    const key = e.key;
    let handled = true;
    if (key === 'ArrowRight' || key === 'ArrowDown') setActive(nearestVisible(1));
    else if (key === 'ArrowLeft' || key === 'ArrowUp') setActive(nearestVisible(-1));
    else if (key === 'Home') setActive(visibleItems()[0]?.index ?? -1);
    else if (key === 'End') setActive(visibleItems().at(-1)?.index ?? -1);
    else if (key === 'Enter' || key === ' ') {
      if (state.active >= 0) setSelected(state.active, true);
    } else if (key === 'Escape') {
      if (state.selected >= 0) setSelected(-1, true);
      setActive(-1, false);
    } else if (key === '+' || key === '=') zoomCentre(1.5);
    else if (key === '-' || key === '_') zoomCentre(1 / 1.5);
    else if (key === '0') resetView();
    else handled = false;
    if (handled) e.preventDefault();
  });

  stage.addEventListener('focus', () => {
    if (state.active < 0 && state.selected >= 0) setActive(state.selected, false);
  });
  stage.addEventListener('blur', () => {
    setActive(-1, false);
  }, { signal });

  // Pointer: hover tooltip, click, drag to pan, wheel and pinch to zoom
  markerLayer.addEventListener('pointerover', (e) => {
    if (e.pointerType !== 'mouse') return;
    const g = e.target.closest?.('.wm-marker');
    if (!g) return;
    const item = items.find((it) => String(it.index) === g.dataset.index);
    if (item && visible[item.layer]) showTooltip(item);
  }, { signal });
  markerLayer.addEventListener('pointerleave', (e) => {
    if (e.pointerType !== 'mouse') return;
    if (state.active < 0) hideTooltip();
  }, { signal });
  markerLayer.addEventListener('pointerout', (e) => {
    if (e.pointerType !== 'mouse') return;
    const g = e.target.closest?.('.wm-marker');
    if (!g || g.contains(e.relatedTarget)) return;
    const keyboardItem = items.find((it) => it.index === state.active);
    if (keyboardItem && visible[keyboardItem.layer]) showTooltip(keyboardItem);
    else hideTooltip();
  }, { signal });

  stage.addEventListener('pointerdown', (e) => {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    suppressClick = false;
    if (pointers.size === 1) {
      drag = { startX: e.clientX, startY: e.clientY, lastX: e.clientX, lastY: e.clientY, moved: false };
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinchStart = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, scale: state.scale };
      drag = null;
    }
  }, { signal });

  stage.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2 && pinchStart) {
      const [a, b] = [...pointers.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const scale = clamp(pinchStart.scale * (distance / pinchStart.distance), MIN_SCALE, MAX_SCALE);
      const mid = toSvg((a.x + b.x) / 2, (a.y + b.y) / 2);
      zoomAt(scale, mid.x, mid.y, 0);
      suppressClick = true;
      return;
    }
    if (drag && pointers.size === 1) {
      const dx = e.clientX - drag.lastX;
      const dy = e.clientY - drag.lastY;
      if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > DRAG_SLOP_PX) {
        drag.moved = true;
        suppressClick = true;
        try { stage.setPointerCapture(e.pointerId); } catch { /* pointer already released */ }
        stage.classList.add('is-dragging');
        hideTooltip();
      }
      if (drag.moved && state.scale > 1) {
        const upp = unitsPerPx();
        state.tx += dx * upp;
        state.ty += dy * upp;
        clampView(state);
        paint();
      }
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
    }
  }, { signal });

  function endPointer(e) {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinchStart = null;
    if (pointers.size === 0) {
      drag = null;
      stage.classList.remove('is-dragging');
    }
  }
  stage.addEventListener('pointerup', endPointer, { signal });
  stage.addEventListener('pointercancel', endPointer, { signal });

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * 0.0015);
    const p = toSvg(e.clientX, e.clientY);
    zoomAt(clamp(state.scale * factor, MIN_SCALE, MAX_SCALE), p.x, p.y, 0);
  }, { passive: false, signal });

  stage.addEventListener('click', (e) => {
    if (suppressClick) return;
    const g = e.target.closest?.('.wm-marker');
    if (g) {
      const index = Number(g.dataset.index);
      setActive(index, false);
      setSelected(index, true);
      return;
    }
    if (state.selected >= 0) setSelected(-1, true);
  }, { signal });

  zoomIn.addEventListener('click', () => zoomCentre(1.5), { signal });
  zoomOut.addEventListener('click', () => zoomCentre(1 / 1.5), { signal });
  resetBtn.addEventListener('click', () => { resetView(); }, { signal });

  // Country outlines load asynchronously. Points are already in the DOM, so the list and keyboard work at once.
  let loaded = false;
  loadOutline()
    .then((paths) => {
      if (destroyed) return;
      countryLayer.replaceChildren(...paths.map((p) => {
        const node = document.importNode(p, true);
        node.setAttribute('class', 'wm-country');
        return node;
      }));
      loaded = true;
      paint();
    })
    .catch(() => {
      if (destroyed) return;
      root.prepend(h('div', { class: 'state-msg empty wm-error', role: 'alert' },
        h('strong', null, 'The country outlines did not load'),
        h('span', null, 'Points are still listed and selectable below the map.')));
    });

  if (typeof ResizeObserver === 'function') {
    resizeObserver = new ResizeObserver(() => { if (!destroyed) paint(); });
    resizeObserver.observe(stage);
  }

  applyLayerVisibility();
  paint();
  if (items.length) fit(0);
  else resetView(0);

  const api = {
    get loaded() { return loaded; },
    counts: { ...counts },
    skipped: skipped.slice(),
    setLayerVisible(layer, on) {
      if (!(layer in visible)) return;
      visible[layer] = !!on;
      applyLayerVisibility();
      paint();
    },
    select(index) {
      setSelected(index === null || index === undefined ? -1 : index, false);
    },
    fit: () => fit(),
    zoomIn: () => zoomCentre(1.5),
    zoomOut: () => zoomCentre(1 / 1.5),
    reset: () => resetView(),
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stopAnimation();
      controller.abort();
      resizeObserver?.disconnect();
      pointers.clear();
      container.replaceChildren();
    },
  };
  return api;
}

// Legend: shape and colour for each layer, with live counts.
export function worldMapLegend({ disaster = 0, logistics = 0 } = {}) {
  const row = (layer, count) => {
    const def = LAYERS[layer];
    const symbol = def.shape === 'diamond'
      ? svgEl('svg', { class: 'wm-legend-symbol', viewBox: '-8 -8 16 16', 'aria-hidden': 'true', focusable: 'false' },
          svgEl('path', { d: 'M0,-6.5 L6.5,0 L0,6.5 L-6.5,0 Z', fill: def.color }))
      : svgEl('svg', { class: 'wm-legend-symbol', viewBox: '-8 -8 16 16', 'aria-hidden': 'true', focusable: 'false' },
          svgEl('circle', { r: 5.5, fill: def.color }));
    return h('li', { class: `wm-legend-item wm-legend-item--${layer}` }, symbol,
      h('span', null, def.label),
      h('span', { class: 'wm-legend-count mono' }, String(count)));
  };
  return h('ul', { class: 'wm-legend', 'aria-label': 'Map legend' },
    row('disaster', disaster),
    row('logistics', logistics),
    h('li', { class: 'wm-legend-item wm-legend-item--note' },
      h('span', { class: 'wm-legend-line', 'aria-hidden': 'true' }),
      h('span', null, 'Country outlines: world-map-data, MIT')));
}
