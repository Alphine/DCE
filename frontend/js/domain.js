// Domain constants and pure helpers: task state machine (docs/api.md §4), data classes (SDD §16.3),
// and data transforms for the map and chart. Nothing here invents values.

export const MAIN_FLOW = [
  'PLANNING', 'AWAITING_APPROVAL', 'QUEUED', 'RUNNING', 'OUTPUT_VALIDATING', 'AWAITING_REVIEW', 'COMPLETED',
];

// Where a branch (failure or rejection) leaves the main flow. CANCELLED and ORPHANED are derived in task.js.
export const BRANCH_PARENT = {
  FAILED_PLANNING: 'PLANNING',
  REJECTED: 'AWAITING_APPROVAL',
  TIMED_OUT: 'RUNNING',
  FAILED_SANDBOX: 'RUNNING',
  REJECTED_OUTPUT: 'OUTPUT_VALIDATING',
};

export const TERMINAL_STATES = new Set([
  'FAILED_PLANNING', 'REJECTED', 'CANCELLED', 'TIMED_OUT', 'FAILED_SANDBOX', 'REJECTED_OUTPUT', 'COMPLETED', 'ORPHANED',
]);

// tone: run (amber, in progress) | live (amber, pulsing) | wait (dashed amber, needs a human) | ok | bad | neutral
export const STATE_META = {
  PLANNING: { label: 'Planning', tone: 'run', glyph: '◐', hint: 'The planner drafts a plan from your instruction.' },
  AWAITING_APPROVAL: { label: 'Awaiting approval', tone: 'wait', glyph: '◷', hint: 'Gate A: a human approves the plan and resource limits. Code is not generated yet.' },
  QUEUED: { label: 'Queued', tone: 'run', glyph: '≡', hint: 'Code is generated and queued for the sandbox.' },
  RUNNING: { label: 'Running', tone: 'live', glyph: '●', hint: 'The generated code runs inside the isolated sandbox.' },
  OUTPUT_VALIDATING: { label: 'Validating output', tone: 'run', glyph: '◈', hint: 'Output files are checked for type, size and hash.' },
  AWAITING_REVIEW: { label: 'Awaiting review', tone: 'wait', glyph: '◷', hint: 'Gate B: a reviewer releases the outputs as results.' },
  COMPLETED: { label: 'Completed', tone: 'ok', glyph: '✓', hint: 'Outputs were released after gate B.' },
  FAILED_PLANNING: { label: 'Planning failed', tone: 'bad', glyph: '✕', hint: 'The model output did not pass plan validation.' },
  REJECTED: { label: 'Rejected at gate A', tone: 'bad', glyph: '✕', hint: 'The plan was rejected. No code ran.' },
  CANCELLED: { label: 'Cancelled', tone: 'bad', glyph: '⊘', hint: 'Stopped by the owner or an admin.' },
  TIMED_OUT: { label: 'Timed out', tone: 'bad', glyph: '!', hint: 'The sandbox run exceeded its time limit.' },
  FAILED_SANDBOX: { label: 'Sandbox failed', tone: 'bad', glyph: '✕', hint: 'The sandbox run failed. See sandbox evidence.' },
  REJECTED_OUTPUT: { label: 'Output rejected', tone: 'bad', glyph: '✕', hint: 'Output files failed validation and were not released.' },
  ORPHANED: { label: 'Orphaned', tone: 'bad', glyph: '?', hint: 'The sandbox run was lost and could not be recovered.' },
};

// SDD §16.3. Every displayed result carries one of these labels.
export const DATA_CLASS = {
  RAW_REPORT: { tone: 'neutral', tip: 'RAW_REPORT: original input, unmodified. Produced at intake.' },
  MODEL_EXTRACTION: { tone: 'neutral', tip: 'MODEL_EXTRACTION: output of a model or parser. Not reviewed yet.' },
  OBSERVATION: { tone: 'neutral', tip: 'OBSERVATION: structured, schema-valid and evidence-linked. Passed automatic validation, not yet human-verified.' },
  VERIFIED_OBSERVATION: { tone: 'ok', tip: 'VERIFIED_OBSERVATION: approved by a human reviewer who did not submit it.' },
  INFERRED_FACT: { tone: 'neutral', tip: 'INFERRED_FACT: derived by a deterministic rule from verified observations. Rule pack version is recorded.' },
  SIMULATED_FACT: { tone: 'sim', tip: 'SIMULATED_FACT: output of a simulation or sandbox model. Never a verified real-world observation.' },
  DECISION: { tone: 'amber', tip: 'DECISION: human-approved recommendation or mission.' },
};

export function toNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value.trim());
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

const LAT_RE = /^(lat|latitude)$/i;
const LON_RE = /^(lon|lng|long|longitude)$/i;
const LABEL_RE = /^(district|location|name|area|kelurahan|kecamatan)$/i;

function coord(value, limit) {
  const n = toNumber(value);
  if (n === null || Math.abs(n) > limit) return null;
  return n;
}

// Returns plotted points and rows whose location is unknown. Never invents coordinates.
// Null, missing, out-of-range and (0,0) placeholder coordinates are treated as unknown.
export function incidentPoints(rows, columns) {
  const names = (columns || []).map((c) => (typeof c === 'string' ? c : c.name));
  const keys = names.length ? names : Object.keys((rows && rows[0]) || {});
  const latCol = keys.find((k) => LAT_RE.test(k));
  const lonCol = keys.find((k) => LON_RE.test(k));
  const labelCol = keys.find((k) => LABEL_RE.test(k)) || keys[0];
  const result = { hasCoordinates: !!(latCol && lonCol), points: [], unknown: [] };

  for (const row of rows || []) {
    const label = row[labelCol] !== undefined && row[labelCol] !== null ? String(row[labelCol]) : '(no label)';
    if (!result.hasCoordinates) {
      result.unknown.push({ label });
      continue;
    }
    const lat = coord(row[latCol], 90);
    const lon = coord(row[lonCol], 180);
    if (lat === null || lon === null || (lat === 0 && lon === 0)) {
      result.unknown.push({ label });
    } else {
      result.points.push({ lat, lon, label, row });
    }
  }
  return result;
}

const FACILITY_RE = /^facility_type$/i;

// A dataset with a facility_type column is a logistics dataset (depots, shelters, warehouses, hubs).
// Any other approved dataset is treated as a disaster dataset. The backend does not tag dataset kinds.
export function datasetKind(columns) {
  const names = colNames(columns);
  return names.some((n) => FACILITY_RE.test(n)) ? 'LOGISTICS' : 'DISASTER';
}

function colNames(columns) {
  return (columns || []).map((c) => (typeof c === 'string' ? c : c.name));
}

// Map points for one dataset layer. Each point carries its label, coordinates, optional facility type,
// the other non-empty columns as details, and the dataset name as source. Unknown locations are listed separately.
export function mapPoints(rows, columns, { layer, source }) {
  const names = colNames(columns);
  const keys = names.length ? names : Object.keys((rows && rows[0]) || {});
  const latCol = keys.find((k) => LAT_RE.test(k));
  const lonCol = keys.find((k) => LON_RE.test(k));
  const labelCol = keys.find((k) => LABEL_RE.test(k)) || keys[0];
  const typeCol = keys.find((k) => FACILITY_RE.test(k));
  const omit = new Set([latCol, lonCol, labelCol, typeCol].filter(Boolean));
  const base = incidentPoints(rows, columns);
  const points = base.points.map((p) => {
    const type = typeCol && p.row[typeCol] !== null && p.row[typeCol] !== undefined ? String(p.row[typeCol]) : undefined;
    const details = keys
      .filter((k) => !omit.has(k) && p.row[k] !== null && p.row[k] !== undefined && p.row[k] !== '')
      .slice(0, 6)
      .map((k) => ({ label: k.replace(/_/g, ' '), value: String(p.row[k]) }));
    return { label: p.label, lat: p.lat, lon: p.lon, layer, type, details, source };
  });
  return { hasCoordinates: base.hasCoordinates, points, unknown: base.unknown };
}

// Mean water depth (cm) per district from dataset rows. Rows without a district or depth are skipped.
export function depthByDistrict(rows) {
  const groups = new Map();
  for (const row of rows || []) {
    const district = row.district;
    const depth = toNumber(row.water_depth_cm);
    if (district === undefined || district === null || depth === null) continue;
    const key = String(district);
    const g = groups.get(key) || { sum: 0, n: 0 };
    g.sum += depth;
    g.n += 1;
    groups.set(key, g);
  }
  return [...groups.entries()]
    .map(([district, g]) => ({ district, value: Math.round((g.sum / g.n) * 10) / 10, n: g.n }))
    .sort((a, b) => b.value - a.value);
}

// Reads depth per district from summary.json. The schema is not in docs/api.md, so this accepts
// a few plausible shapes and returns null when none match.
export function depthFromSummary(summary) {
  if (!summary || typeof summary !== 'object') return null;
  const candidates = [summary.water_depth_by_district, summary.districts, summary.by_district];
  for (const c of candidates) {
    let rows = [];
    if (Array.isArray(c)) {
      rows = c.map((item) => ({
        district: item && (item.district ?? item.name),
        value: toNumber(item && (item.water_depth_cm ?? item.avg_water_depth_cm ?? item.mean_water_depth_cm ?? item.value)),
      }));
    } else if (c && typeof c === 'object') {
      rows = Object.entries(c).map(([district, v]) => ({
        district,
        value: toNumber(typeof v === 'object' && v !== null ? (v.water_depth_cm ?? v.mean ?? v.value) : v),
      }));
    }
    rows = rows.filter((r) => r.district !== undefined && r.district !== null && r.value !== null);
    if (rows.length) {
      return rows.map((r) => ({ district: String(r.district), value: r.value, n: null })).sort((a, b) => b.value - a.value);
    }
  }
  return null;
}

// Derive where a CANCELLED or ORPHANED task stopped, from the data the API returns.
export function derivedBranchParent(task) {
  if (task.sandbox) return 'RUNNING';
  const approvedA = (task.approvals || []).some((a) => a.gate === 'A' && a.decision === 'approve');
  if (task.code_sha256 || approvedA) return 'QUEUED';
  if (task.plan) return 'AWAITING_APPROVAL';
  return 'PLANNING';
}
