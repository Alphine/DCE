import { h, pageHead, panel, emptyState } from '../dom.js';
import { hasRole } from '../session.js';

// Honest placeholders. Nothing on these screens is data, estimate or AI output.
// "today" lists the working pages that cover part of the same need.
const FEATURES = {
  situation: {
    title: 'Situation',
    text: 'A live picture of active hazards, affected areas and critical facilities.',
    today: [{ href: '#/', label: 'Command Center', min: 'Viewer', note: 'the map of approved datasets' }],
  },
  analysis: {
    title: 'Analysis',
    text: 'Structured analysis of approved datasets, cascading hazards and resource needs.',
    today: [{ href: '#/agent', label: 'Agent', min: 'Analyst', note: 'sandboxed analysis tasks' }],
  },
  planning: {
    title: 'Planning',
    text: 'Response plans, each one approved at gate A before any code runs.',
    today: [{ href: '#/agent', label: 'Agent', min: 'Analyst', note: 'plans are drafted and gated there' }],
  },
  resources: {
    title: 'Resources',
    text: 'Personnel, vehicles, supplies and shelters, with their current status.',
    today: [{ href: '#/datasets', label: 'Datasets', min: 'Viewer', note: 'logistics sites come from a CSV with a facility_type column' }],
  },
  missions: {
    title: 'Missions',
    text: 'Tracking of agent missions from request to released outputs.',
    today: [{ href: '#/', label: 'Command Center', min: 'Viewer', note: 'recent agent tasks are listed there' }],
  },
  simulation: {
    title: 'Simulation',
    text: 'Scenario projections for flood and tsunami impact.',
    today: [{ href: '#/agent', label: 'Agent', min: 'Analyst', note: 'sandbox runs produce simulated outputs' }],
  },
  reports: {
    title: 'Reports',
    text: 'Situation reports and released documents.',
    today: [{ href: '#/artifacts', label: 'Artifacts', min: 'Viewer', note: 'files from agent tasks, each with a SHA-256' }],
  },
};

// ctx: { user, params: { key } }. Reached only from the routes that call soon() in app.js.
export async function mount(root, ctx) {
  const feature = FEATURES[ctx.params.key] || { title: 'Coming soon', text: 'This screen is not built yet.', today: [] };
  const links = feature.today.filter((t) => hasRole(ctx.user, t.min));

  root.append(...[
    pageHead(feature.title, 'This screen is not built yet.'),
    panel({ title: 'Coming soon', sub: feature.text, cls: 'coming-soon' },
      emptyState('Not built yet', 'No data is shown on this screen yet. Nothing here is estimated or generated.')),
    links.length
      ? panel({ title: 'Available today', sub: 'Working pages that cover part of this need.' },
          h('ul', { class: 'about-list today-list' }, links.map((t) => h('li', null,
            h('a', { href: t.href }, t.label),
            ` · ${t.note}`))))
      : null,
  ].filter(Boolean));

  return () => {};
}
