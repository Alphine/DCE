# Empty states and phone lists (agent EMPTY)

## Files

- `frontend/js/components/empty-state.js` (new): `richEmpty({title, detail, icon, actions})`.
  Icons: `alerts`, `reports`, `datasets`, `missions`, `logistics`, `simulation`, `none` (default and fallback).
  Builds nodes with createElement/createElementNS only. Has `role="status"`. Keeps at most two actions.
  Action hrefs must be in-app hashes (`#/...` or `#id`); anything else is dropped.
- `frontend/js/dom.js`: `emptyState(title, detail, options)`. Without `options`, the markup is unchanged.
  `options = {icon, actions}` renders `richEmpty`. `actions` is `[{label, href}]`, max two.
  dom.js imports richEmpty; empty-state.js imports nothing, so there is no cycle.
- `frontend/css/empty.css` (new): empty-state styles, `.stack-list`, and the `.card-rows` phone layout.
- Call sites with options: `views/reports.js`, `missions.js`, `alerts.js`, `datasets.js`, `simulation.js`,
  `hazards.js`, `logistics.js`. Wording is unchanged.

## Phone card convention (`.card-rows`)

Below 640 px, a table with class `card-rows` shows each row as a card:

- Put `class="card-rows"` on the `<table>`. It must sit inside `.table-wrap`.
- Put `data-label="Column name"` on every `<td>`, matching its `<th>` text. The label appears before the value.
- The `<thead>` is visually hidden on phones. It stays in the DOM for screen readers.
- Above 640 px nothing changes. Tables without the class are not affected.

Example: `<td data-label="Hazard">Flood</td>`

Existing tables have not been converted. The owner applies `card-rows` and `data-label` per table.

## Owner requests

- Add to `frontend/index.html` or `app.js` (wherever the other stylesheets are linked): `<link rel="stylesheet" href="css/empty.css">`.
- Actions on the Datasets, Reports and Simulation empty states point to other screens, and some point to the same
  screen. Replace them with in-page anchors if you prefer, for example a field-report form anchor.
- Confirm the Situation/Datasets/Planning/Reports routes fit the wording. Action labels are "Open X" and use existing hashes.
- Optional: apply `card-rows` to the Reports, Missions and Simulation tables.
