# Runs screens: Simulation, Planning, Missions

## What each screen shows on open

- **Simulation** (`frontend/js/views/simulation.js`): the newest run's detail. Tiles, hour-by-hour timeline chart with its table, peak-by-district table, inputs and reproducibility panel, assumptions, and the link to Planning. The run list sits below. The "New scenario" form is a collapsed `details` element. It opens by itself when there are no runs.
- **Planning** (`frontend/js/views/planning.js`): the newest run's allocation. Totals, a priority table with household bars, "What to do next" (links to Missions with the run name), not-estimated items, assumptions, and basis.
- **Missions** (`frontend/js/views/missions.js`): the newest mission's detail. Objective, source, target-area chips, decision history, and approve or reject for Approvers who did not propose it. The proposal form is collapsed. It opens when there are no missions, or when it arrives from Planning.

## Endpoints

- `GET /api/simulations`, `GET /api/simulations/{id}`, `POST /api/simulations`
- `GET /api/planning/allocation?simulation_id=`
- `GET /api/missions`, `GET /api/missions/{id}`, `POST /api/missions`, `POST /api/missions/{id}/approve|reject`
- Offline lists still go through `loadList` (`simulations`, `missions`).

## Handoff from Planning to Missions

`#/missions?run=<simulation name>&simulation=<id>` prefills the proposal title (`Response to <run>`) and objective. The run name is set as an input value, never as HTML.

## Roles

- Run form and proposal form: Analyst and above.
- Approve and reject: Approver and above, and never the proposer. The UI shows a note to the proposer and to non-approvers instead.

## Stylesheet

`frontend/css/runs.css` must be linked from `index.html` and added to the precache in `sw.js`. Both are owned outside this change.
