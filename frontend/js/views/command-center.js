import { api } from '../api.js';
import { h, clear, fmtDate, short, spinner, errorState, listOf, pageHead, panel, emptyState, alertBox, kv } from '../dom.js';
import { STATE_META, datasetKind, mapPoints, depthByDistrict, depthFromSummary, toNumber } from '../domain.js';
import { stateBadge, dataClassBadge, badge } from '../components/badges.js';
import { createWorldMap, worldMapLegend, pointDescription } from '../components/world-map.js';
import { createBarChart } from '../components/chart.js';
import { verifyBlob, hashStatus } from '../components/hash.js';
import { toast } from '../components/toast.js';
import { go } from '../router.js';

// Command Center: summary tiles, world map (disaster and logistics layers), depth chart, recent task feed.
export async function mount(root, ctx) {
  const { signal } = ctx;
  let map = null;
  let chart = null;
  let pointCard = null;

  const tilesSlot = h('div', { class: 'tiles' }, spinner('Loading summary…'));
  const mapSlot = h('div', { class: 'stack' });
  const chartSlot = h('div', { class: 'stack' });
  const feedSlot = h('div', null, spinner('Loading tasks…'));
  const refreshBtn = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => load() }, 'Refresh');

  root.append(
    pageHead('Command Center',
      'Datasets, agent tasks, sandbox status and quota at a glance. Map and chart use the first approved dataset.',
      refreshBtn),
    tilesSlot,
    h('div', { class: 'grid-2' },
      panel({ title: 'Disaster and logistics map', sub: 'Incident points and logistics sites from approved datasets, only where coordinates are present.', cls: '', style: '--i:3' }, mapSlot),
      panel({ title: 'Water depth by district', sub: 'Mean depth in cm, drawn from validated data.', style: '--i:4' }, chartSlot)),
    panel({ title: 'Recent agent tasks', sub: 'Your tasks. Reviewers see all tasks.', style: '--i:5' }, feedSlot));

  function renderTiles(s) {
    const by = (s.tasks && s.tasks.by_state) || {};
    const total = Object.values(by).reduce((acc, n) => acc + (Number(n) || 0), 0);
    const running = by.RUNNING || 0;
    const waiting = (by.AWAITING_APPROVAL || 0) + (by.AWAITING_REVIEW || 0);
    const used = (s.quota && s.quota.used_today) || 0;
    const limit = (s.quota && s.quota.limit) || 0;
    const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    const sandbox = s.sandbox || {};
    const inference = s.inference || {};
    const isLocal = sandbox.runner === 'local';

    const tile = (i, label, value, sub, cls = '') => h('article', { class: `tile ${cls}`.trim(), style: `--i:${i}` },
      h('div', { class: 'tile-label' }, label),
      h('div', { class: 'tile-value' }, value),
      h('div', { class: 'tile-sub' }, sub));

    const quotaTile = h('article', { class: 'tile', style: '--i:5' },
      h('div', { class: 'tile-label' }, 'Agent quota today'),
      h('div', { class: 'tile-value' }, `${used}/${limit || '—'}`),
      h('div', { class: 'tile-sub' }, limit ? `${Math.max(0, limit - used)} remaining` : 'No limit reported'),
      h('div', {
        class: 'meter', role: 'meter', 'aria-label': 'Daily agent task quota used',
        'aria-valuemin': '0', 'aria-valuemax': String(limit || 0), 'aria-valuenow': String(used),
      }, h('span', { style: `width:${pct}%` })));

    tilesSlot.replaceChildren(
      tile(0, 'Datasets', s.datasets ? s.datasets.total ?? 0 : 0, `${(s.datasets && s.datasets.approved) || 0} approved`),
      tile(1, 'Agent tasks', total, `${running} running, ${waiting} waiting on a gate`, 'tile--amber'),
      tile(2, 'Artifacts', s.artifacts ?? 0, 'Files with recorded SHA-256', 'tile--sim'),
      h('article', { class: 'tile', style: '--i:3' },
        h('div', { class: 'tile-label' }, 'Sandbox'),
        h('div', { class: 'tile-value' }, `${sandbox.running ?? 0}/${sandbox.max_concurrent ?? 0}`),
        h('div', { class: 'tile-sub' },
          h('span', null, `Runner: ${sandbox.runner || 'unknown'}`),
          isLocal ? h('span', { class: 'badge badge--bad', style: 'margin-left:8px' }, 'DEV ONLY') : null)),
      h('article', { class: 'tile', style: '--i:4' },
        h('div', { class: 'tile-label' }, 'Inference'),
        h('div', { class: 'tile-value', style: 'font-size:1.35rem' }, inference.mode || 'unknown'),
        h('div', { class: 'tile-sub' },
          inference.mode === 'mock'
            ? 'Mock planner: deterministic outputs, not a live model.'
            : `Model: ${inference.model || 'not set'}`)),
      quotaTile);
  }

  function renderFeed(tasks) {
    const sorted = [...tasks].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, 8);
    if (!sorted.length) {
      feedSlot.replaceChildren(emptyState('No agent tasks yet', 'Start one from the Agent screen.'));
      return;
    }
    feedSlot.replaceChildren(h('div', null, sorted.map((t) => h('a', { class: 'feed-row', href: `#/tasks/${encodeURIComponent(t.id)}` },
      h('span', { class: 'feed-title' }, short(t.instruction, 110)),
      stateBadge(t.state),
      h('span', { class: 'feed-meta' },
        h('span', { class: 'mono' }, short(t.id, 8)),
        h('span', null, `by ${(t.owner && t.owner.username) || 'unknown'}`),
        h('span', null, fmtDate(t.created_at)))))));
  }

  // Find the newest summary.json among recent completed tasks. Its hash is checked before use.
  async function findSummary(tasks) {
    const candidates = tasks.filter((t) => t.state === 'COMPLETED' || t.state === 'AWAITING_REVIEW').slice(0, 5);
    for (const t of candidates) {
      try {
        const artifacts = listOf(await api.get(`agent/tasks/${encodeURIComponent(t.id)}/artifacts`, { signal }));
        const file = artifacts.find((a) => a.name === 'summary.json');
        if (!file) continue;
        const { blob, sha256 } = await api.blob(`artifacts/${encodeURIComponent(file.id)}`, { signal });
        const check = await verifyBlob(blob, sha256 || file.sha256);
        if (check.status === 'mismatch') continue;
        const data = JSON.parse(await blob.text());
        const rows = depthFromSummary(data);
        if (rows && rows.length) return { rows, task: t, check };
      } catch (err) {
        if (signal.aborted || err.name === 'AbortError') throw err;
        // Unreadable or non-JSON summary: try the next task.
      }
    }
    return null;
  }

  // Approved datasets, classified by their profile: a facility_type column marks logistics, anything else is disaster.
  async function loadApproved() {
    const datasetsRes = await api.get('datasets', { signal });
    if (signal.aborted) return null;
    const approved = listOf(datasetsRes).filter((d) => d.status === 'APPROVED').slice(0, 8);
    const details = await Promise.all(approved.map((d) => api.get(`datasets/${encodeURIComponent(d.id)}`, { signal })));
    if (signal.aborted) return null;
    return details.map((detail) => {
      const columns = (detail.profile && detail.profile.columns) || [];
      return { id: detail.id, name: detail.name, columns, kind: datasetKind(columns) };
    });
  }

  async function loadRows(ds) {
    // Full rows (contract §12), not the 5-row preview, so every located point can be plotted.
    const res = await api.get(`datasets/${encodeURIComponent(ds.id)}/rows?limit=1000`, { signal });
    return (res && res.items) || [];
  }

  function showPointCard(point) {
    if (!point) {
      pointCard.replaceChildren(h('p', { class: 'small muted' },
        'Select a point on the map, or focus the map and press Enter, to see its details here.'));
      return;
    }
    const d = pointDescription(point);
    pointCard.replaceChildren(
      h('h3', { class: 'wm-card-title' }, point.label),
      h('p', { class: 'small' }, `${d.layerLabel}${point.type ? ` · ${point.type}` : ''}`),
      h('dl', { class: 'wm-card-dl' },
        kv('Coordinates', d.coords),
        kv('Source dataset', point.source || '—'),
        ...(point.details || []).map((line) => kv(line.label, line.value))));
  }

  async function renderSpatial(tasks) {
    const datasets = await loadApproved();
    if (!datasets) return;
    const disasterDs = datasets.find((d) => d.kind === 'DISASTER') || null;
    const logisticsDs = datasets.find((d) => d.kind === 'LOGISTICS') || null;
    const [disasterRows, logisticsRows] = await Promise.all([
      disasterDs ? loadRows(disasterDs) : [],
      logisticsDs ? loadRows(logisticsDs) : [],
    ]);
    if (signal.aborted) return;
    const rows = disasterRows;

    // Map
    if (map) map.destroy();
    map = null;
    pointCard = h('div', { class: 'wm-card', 'aria-live': 'polite' });
    if (!disasterDs && !logisticsDs) {
      mapSlot.replaceChildren(emptyState('No approved dataset yet', 'Approve a dataset to plot its incidents or logistics sites.'));
    } else {
      const dis = disasterDs ? mapPoints(disasterRows, disasterDs.columns, { layer: 'disaster', source: disasterDs.name }) : null;
      const log = logisticsDs ? mapPoints(logisticsRows, logisticsDs.columns, { layer: 'logistics', source: logisticsDs.name }) : null;
      const disCount = dis ? dis.points.length : 0;
      const logCount = log ? log.points.length : 0;
      const mapHost = h('div', { class: 'wm-host', 'aria-label': 'Disaster and logistics map' });
      const toggle = (layer, label, count) => {
        const input = h('input', { type: 'checkbox', checked: true, disabled: count === 0 ? true : null });
        input.addEventListener('change', () => { if (map) map.setLayerVisible(layer, input.checked); });
        return h('label', { class: 'wm-toggle' }, input, h('span', null, `${label} (${count})`));
      };
      const unknownList = dis && dis.unknown.length
        ? h('details', null,
            h('summary', null, `${dis.unknown.length} disaster location unknown (not plotted)`),
            h('ul', { class: 'about-list' }, dis.unknown.map((u) => h('li', null, u.label))))
        : null;
      const logisticsNotice = logisticsDs
        ? h('p', { class: 'small muted' },
            `${logCount} logistics sites plotted from ${logisticsDs.name}.`,
            log && log.unknown.length ? ` ${log.unknown.length} without coordinates (not plotted).` : null)
        : h('p', { class: 'small' },
            'No approved logistics dataset yet. Upload a CSV with a facility_type column on the ',
            h('a', { href: '#/datasets' }, 'Datasets page'), ', then approve it.');
      mapSlot.replaceChildren(
        h('div', { class: 'wm-toolbar', role: 'group', 'aria-label': 'Map layers' },
          toggle('disaster', 'Disaster incidents', disCount),
          toggle('logistics', 'Logistics sites', logCount)),
        mapHost,
        worldMapLegend({ disaster: disCount, logistics: logCount }),
        h('p', { class: 'small muted' },
          dis
            ? `${disCount} disaster points plotted from ${disasterDs.name} (${disasterRows.length} rows loaded). `
            : 'No approved disaster dataset yet. ',
          dis && !dis.hasCoordinates ? 'That dataset has no latitude and longitude columns, so no points are plotted.' : null),
        unknownList,
        logisticsNotice,
        pointCard);
      showPointCard(null);
      const points = [...(dis ? dis.points : []), ...(log ? log.points : [])];
      map = createWorldMap(mapHost, {
        points,
        layers: { disaster: true, logistics: true },
        onSelect: (point) => showPointCard(point),
      });
      if (!points.length) mapHost.prepend(h('p', { class: 'small muted wm-empty' }, 'No points with coordinates to plot.'));
    }

    // Chart: summary.json when a verified one exists, else the dataset preview.
    if (chart) chart.destroy();
    chart = null;
    const fromSummary = await findSummary(tasks);
    if (signal.aborted) return;
    let series = null;
    let sourceNode;
    if (fromSummary) {
      series = fromSummary.rows;
      sourceNode = h('div', { class: 'row small' },
        dataClassBadge('SIMULATED_FACT'),
        h('span', { class: 'muted' }, `From summary.json of task ${short(fromSummary.task.id, 8)}`),
        hashStatus(fromSummary.check));
    } else {
      series = depthByDistrict(rows).map((r) => ({ district: r.district, value: r.value, n: r.n }));
      sourceNode = h('div', { class: 'row small' },
        dataClassBadge('RAW_REPORT'),
        h('span', { class: 'muted' }, 'Mean of the approved dataset rows. No validated summary yet.'));
    }

    if (!series || !series.length) {
      chartSlot.replaceChildren(sourceNode, emptyState('No water depth data', 'The approved dataset has no district and water_depth_cm values.'));
      return;
    }
    const canvas = h('canvas', { role: 'img', 'aria-label': `Bar chart of water depth in centimetres for ${series.length} districts` });
    const box = h('div', { class: 'chart-box' }, canvas);
    chartSlot.replaceChildren(sourceNode, box);
    chart = createBarChart(canvas, {
      labels: series.map((s) => s.district),
      values: series.map((s) => s.value),
      label: 'Water depth (cm)',
      unit: 'cm',
    });
    if (!chart) box.replaceChildren(h('div', { class: 'state-msg' }, 'Chart library did not load. Values are listed below.'),
      h('ul', { class: 'about-list' }, series.map((s) => h('li', null, `${s.district}: ${s.value} cm`))));
  }

  async function load() {
    refreshBtn.disabled = true;
    try {
      const [summary, tasksRes] = await Promise.all([
        api.get('dashboard/summary', { signal }),
        api.get('agent/tasks', { signal }),
      ]);
      if (signal.aborted) return;
      const tasks = listOf(tasksRes);
      renderTiles(summary);
      renderFeed(tasks);
      await renderSpatial(tasks);
    } catch (err) {
      if (signal.aborted || err.name === 'AbortError') return;
      tilesSlot.replaceChildren(errorState(err, load));
      toast(err.message, { kind: 'error' });
    } finally {
      refreshBtn.disabled = false;
    }
  }

  load();

  return () => {
    if (map) map.destroy();
    if (chart) chart.destroy();
    clear(root);
  };
}
