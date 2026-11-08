import { h, pageHead, panel } from '../dom.js';

// Static content only: no user or API data is interpolated into this markup.
const TRUST_SVG = `
<svg viewBox="0 0 960 360" role="img" aria-labelledby="trust-title trust-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="trust-title">Trust boundary between the trusted app domain and the untrusted sandbox</title>
  <desc id="trust-desc">The trusted domain holds the frontend, API, database, audit log and inference adapter. The untrusted sandbox domain runs generated code in a container with no network. Only named inputs go in and only validated files come out.</desc>
  <defs>
    <marker id="arrow-amber" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow-amber"/></marker>
    <marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow-red"/></marker>
  </defs>
  <rect x="20" y="20" width="400" height="320" rx="16" class="zone-trusted"/>
  <text x="40" y="52" class="svg-kicker">TRUSTED DOMAIN · app host</text>
  <rect x="50" y="80" width="150" height="58" rx="10" class="node"/>
  <text x="125" y="105" text-anchor="middle" class="svg-t">Frontend</text>
  <text x="125" y="124" text-anchor="middle" class="svg-s">static, /api only</text>
  <rect x="240" y="80" width="150" height="58" rx="10" class="node"/>
  <text x="315" y="105" text-anchor="middle" class="svg-t">FastAPI app</text>
  <text x="315" y="124" text-anchor="middle" class="svg-s">auth, plan gates, state</text>
  <rect x="50" y="176" width="150" height="58" rx="10" class="node"/>
  <text x="125" y="201" text-anchor="middle" class="svg-t">Audit + SQLite</text>
  <text x="125" y="220" text-anchor="middle" class="svg-s">hash-chained, append-only</text>
  <rect x="240" y="176" width="150" height="58" rx="10" class="node"/>
  <text x="315" y="201" text-anchor="middle" class="svg-t">Inference adapter</text>
  <text x="315" y="220" text-anchor="middle" class="svg-s">key never leaves here</text>
  <line x1="200" y1="109" x2="240" y2="109" class="edge"/>
  <line x1="125" y1="138" x2="125" y2="176" class="edge"/>
  <line x1="315" y1="138" x2="315" y2="176" class="edge-dash"/>
  <text x="125" y="290" class="svg-s">Plan and code are never run in this domain.</text>

  <line x1="430" y1="20" x2="430" y2="340" class="boundary"/>
  <text x="446" y="36" class="svg-boundary">TRUST BOUNDARY</text>

  <rect x="540" y="20" width="400" height="320" rx="16" class="zone-untrusted"/>
  <text x="560" y="52" class="svg-kicker svg-kicker--red">UNTRUSTED DOMAIN · sandbox</text>
  <rect x="580" y="80" width="320" height="82" rx="10" class="node node--red"/>
  <text x="740" y="108" text-anchor="middle" class="svg-t">Sandbox container</text>
  <text x="740" y="128" text-anchor="middle" class="svg-s">no network · read-only root · non-root user</text>
  <text x="740" y="146" text-anchor="middle" class="svg-s">memory, pids and time limits from the plan</text>
  <rect x="580" y="196" width="320" height="58" rx="10" class="node node--red"/>
  <text x="740" y="221" text-anchor="middle" class="svg-t">Generated task.py</text>
  <text x="740" y="240" text-anchor="middle" class="svg-s">its SHA-256 is recorded before the run</text>
  <line x1="740" y1="162" x2="740" y2="196" class="edge-dash"/>

  <path d="M400 110 C 470 110, 500 110, 580 110" class="flow-in" marker-end="url(#arrow-amber)"/>
  <text x="488" y="96" text-anchor="middle" class="svg-s">named inputs only</text>
  <path d="M580 150 C 520 150, 500 150, 400 150" class="flow-out" marker-end="url(#arrow-red)"/>
  <text x="488" y="170" text-anchor="middle" class="svg-s">stdout, files in /out</text>
  <text x="740" y="300" text-anchor="middle" class="svg-s">Outputs return only as hashed files.</text>
  <text x="740" y="320" text-anchor="middle" class="svg-s">Hash checked and validated before they are shown.</text>
</svg>`;

const STATE_SVG = `
<svg viewBox="0 0 960 300" role="img" aria-labelledby="fsm-title fsm-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="fsm-title">Task state machine</title>
  <desc id="fsm-desc">Main flow: PLANNING, AWAITING_APPROVAL (gate A), QUEUED, RUNNING, OUTPUT_VALIDATING, AWAITING_REVIEW (gate B), COMPLETED. Branches: FAILED_PLANNING, REJECTED, TIMED_OUT, FAILED_SANDBOX, REJECTED_OUTPUT.</desc>
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="arrow-amber"/></marker>
    <marker id="arr-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="arrow-red"/></marker>
  </defs>
  <g class="fsm-main">
    <rect x="20" y="30" width="114" height="46" rx="10" class="node"/><text x="77" y="58" text-anchor="middle" class="svg-s">PLANNING</text>
    <rect x="164" y="30" width="114" height="46" rx="10" class="node node--gate"/><text x="221" y="50" text-anchor="middle" class="svg-s">AWAITING_APPROVAL</text><text x="221" y="66" text-anchor="middle" class="svg-gate">gate A</text>
    <rect x="308" y="30" width="114" height="46" rx="10" class="node"/><text x="365" y="58" text-anchor="middle" class="svg-s">QUEUED</text>
    <rect x="452" y="30" width="114" height="46" rx="10" class="node"/><text x="509" y="58" text-anchor="middle" class="svg-s">RUNNING</text>
    <rect x="596" y="30" width="114" height="46" rx="10" class="node"/><text x="653" y="50" text-anchor="middle" class="svg-s">OUTPUT_</text><text x="653" y="66" text-anchor="middle" class="svg-s">VALIDATING</text>
    <rect x="740" y="30" width="96" height="46" rx="10" class="node node--gate"/><text x="788" y="50" text-anchor="middle" class="svg-s">AWAITING_</text><text x="788" y="66" text-anchor="middle" class="svg-gate">REVIEW · gate B</text>
    <rect x="860" y="30" width="80" height="46" rx="10" class="node node--ok"/><text x="900" y="58" text-anchor="middle" class="svg-s">COMPLETED</text>
  </g>
  <g class="fsm-edges">
    <line x1="134" y1="53" x2="162" y2="53" marker-end="url(#arr)" class="edge"/>
    <line x1="278" y1="53" x2="306" y2="53" marker-end="url(#arr)" class="edge"/>
    <line x1="422" y1="53" x2="450" y2="53" marker-end="url(#arr)" class="edge"/>
    <line x1="566" y1="53" x2="594" y2="53" marker-end="url(#arr)" class="edge"/>
    <line x1="710" y1="53" x2="738" y2="53" marker-end="url(#arr)" class="edge"/>
    <line x1="836" y1="53" x2="858" y2="53" marker-end="url(#arr)" class="edge"/>
  </g>
  <g class="fsm-branch">
    <line x1="77" y1="76" x2="77" y2="150" marker-end="url(#arr-red)" class="edge-red"/>
    <rect x="20" y="150" width="114" height="42" rx="10" class="node node--red"/><text x="77" y="175" text-anchor="middle" class="svg-s">FAILED_PLANNING</text>
    <line x1="221" y1="76" x2="221" y2="150" marker-end="url(#arr-red)" class="edge-red"/>
    <rect x="164" y="150" width="114" height="42" rx="10" class="node node--red"/><text x="221" y="175" text-anchor="middle" class="svg-s">REJECTED</text>
    <line x1="500" y1="76" x2="450" y2="150" marker-end="url(#arr-red)" class="edge-red"/>
    <rect x="370" y="150" width="114" height="42" rx="10" class="node node--red"/><text x="427" y="175" text-anchor="middle" class="svg-s">TIMED_OUT</text>
    <line x1="520" y1="76" x2="540" y2="150" marker-end="url(#arr-red)" class="edge-red"/>
    <rect x="520" y="150" width="130" height="42" rx="10" class="node node--red"/><text x="585" y="175" text-anchor="middle" class="svg-s">FAILED_SANDBOX</text>
    <line x1="653" y1="76" x2="653" y2="150" marker-end="url(#arr-red)" class="edge-red"/>
    <rect x="596" y="150" width="114" height="42" rx="10" class="node node--red"/><text x="653" y="168" text-anchor="middle" class="svg-s">REJECTED_</text><text x="653" y="184" text-anchor="middle" class="svg-s">OUTPUT</text>
  </g>
  <text x="20" y="235" class="svg-s">Dashed red nodes are terminal branches. Any non-terminal state can also move to CANCELLED (owner or admin), and a lost run can end as ORPHANED.</text>
  <text x="20" y="258" class="svg-s">Gate A approves the plan and limits. Code is generated after gate A, inside QUEUED. Gate B releases validated outputs as results.</text>
  <text x="20" y="281" class="svg-s">Invalid transitions return 409 INVALID_STATE. Every transition is written to the audit log.</text>
</svg>`;

export async function mount(root, ctx) {
  // Static markup above, no interpolated data.
  const figureTrust = h('figure', { class: 'arch-figure' });
  figureTrust.innerHTML = TRUST_SVG;
  figureTrust.append(h('figcaption', null, 'The sandbox receives only the inputs named in the approved plan. It never receives the inference key, the database or the audit log.'));
  const figureFsm = h('figure', { class: 'arch-figure' });
  figureFsm.innerHTML = STATE_SVG;

  root.append(
    pageHead('Architecture',
      'Blast Radius Zero: generated code runs in a box with no route to the app, the key or the data. Only hashed outputs come back.'),
    panel({ title: 'Trust boundary', sub: 'What crosses the line, and what never does.', style: '--i:1' },
      figureTrust),
    panel({ title: 'Task state machine', sub: 'Two human gates. Failures are visible branches, not silent errors.', style: '--i:2' },
      figureFsm),
    h('div', { class: 'about-grid' },
      panel({ title: 'Data classes', style: '--i:3' },
        h('table', { class: 'table dc-table' },
          h('caption', { class: 'sr-only' }, 'Data classes and their meaning'),
          h('tbody', null,
            dcRow('RAW_REPORT', 'Original input, unmodified.'),
            dcRow('MODEL_EXTRACTION', 'Output of a model or parser, unreviewed.'),
            dcRow('OBSERVATION', 'Schema-valid and evidence-linked. Not yet human-verified.'),
            dcRow('VERIFIED_OBSERVATION', 'Approved by a reviewer who did not submit it.'),
            dcRow('INFERRED_FACT', 'Derived by a deterministic rule from verified observations.'),
            dcRow('SIMULATED_FACT', 'Output of a simulation or sandbox run. Never a verified observation.'),
            dcRow('DECISION', 'Human-approved recommendation or mission.')))),
      panel({ title: 'Roles', style: '--i:4' },
        h('table', { class: 'table' },
          h('caption', { class: 'sr-only' }, 'Roles and what they can do'),
          h('tbody', null,
            roleRow('Viewer', 'Read dashboards, approved data and results shared with them.'),
            roleRow('Analyst', 'Upload datasets and submit agent tasks within quota.'),
            roleRow('Reviewer', 'Approve datasets and gate B, read the audit log. Not own work.'),
            roleRow('Approver', 'Approve gate A and missions. Not own work.'),
            roleRow('Admin', 'Manage users, verify the audit chain, cancel tasks.')))),
      panel({ title: 'Honest limits', style: '--i:5' },
        h('ul', { class: 'about-list' },
          h('li', null, 'Mock inference is deterministic. It is a planner stand-in, not a live model.'),
          h('li', null, 'The local sandbox runner is for development only. It has no container isolation.'),
          h('li', null, 'Hash checks in the browser need HTTPS or localhost.'),
          h('li', null, 'Gate A approves the plan and limits, not the generated code.'),
          h('li', null, 'Map points come only from real coordinates. Missing coordinates are listed, never plotted.'))),
      panel({ title: 'Map and data sources', sub: 'Where the map outlines and libraries come from, and their licences.', style: '--i:6' },
        h('ul', { class: 'about-list' },
          h('li', null, 'Country outlines: Natural Earth 1:110m Admin 0 (countries). Public domain. ',
            h('a', { href: 'https://www.naturalearthdata.com/about/terms-of-use/', target: '_blank', rel: 'noopener noreferrer' }, 'Terms of use')),
          h('li', null, 'Map library: Leaflet 1.9.4, BSD 2-Clause licence, copyright Volodymyr Agafonkin and CloudMade contributors. Bundled with the app, not loaded from a CDN. ',
            h('a', { href: 'https://leafletjs.com', target: '_blank', rel: 'noopener noreferrer' }, 'leafletjs.com')),
          h('li', null, 'No online map tiles are loaded. The map shows vector outlines and the data you approved.'),
          h('li', null, 'Each source keeps its own licence. The two above are the only map data the Situation and Command Center maps use.'),
          h('li', null, 'Disaster Commander Edge itself is released under the MIT licence. See the LICENSE file in the repository.')))));

  return () => {};
}

function dcRow(cls, text) {
  return h('tr', null, h('td', null, h('span', { class: 'dc dc--neutral' }, cls)), h('td', null, text));
}

function roleRow(role, text) {
  return h('tr', null, h('td', { class: 'mono' }, role), h('td', null, text));
}
