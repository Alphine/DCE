# Frontend / backend API contract audit (AUD-CONTRACT)

Branch: feature/offline-global. Scope: `frontend/js/views/`, `frontend/js/components/`, `frontend/js/offline/`, `frontend/js/api.js`.
`views/command-center.js` was not edited (owned by another agent). Backend was not edited.

## Method

1. Listed every call site with `api.get / post / patch / postEmpty / upload / blob` under `frontend/js`, plus the offline `loadList` cache reads and the outbox kinds.
2. Dumped the live OpenAPI schema from `create_app()` (69 method+path pairs, including the `/api` prefix from `main.py`). Compared each call's method, path, body keys (`extra="forbid"` models), query keys, and the response keys the view reads against the route code (`backend/app/routes/*.py`, `backend/app/agent/views.py`, `backend/app/rules/*.py`, `backend/app/alerts.py`, `backend/app/routes/sync.py`).
3. Checked pending and error states for every view that shows a spinner.

## Counts

- Direct call sites checked: **72** (across 22 files), plus 4 cached list loads (`loadList`) and the outbox replay path (5 kinds, `sync/batch`).
- Distinct method+path pairs used by the frontend: **33**. All of them exist in the backend with the expected method.

| Class | Count | Notes |
|---|---|---|
| WRONG_PATH | 0 | |
| WRONG_METHOD | 0 | |
| BODY_FIELD | 0 | All bodies match their `extra="forbid"` models; required fields are present. Argument order for `api.post(path, json, opts)` is correct at all 33 post/patch sites. |
| RESPONSE_FIELD | 4 | Fixed (see below). |
| ROLE | 0 | Each UI gate matches the backend role check (Analyst write, Reviewer ack/review/gate B, Approver mission decide and gate A, Admin users/verify, owner-or-Admin cancel). |
| MISSING_ENDPOINT | 0 | Every frontend call has a backend route. |
| Other (UI consistency) | 1 | Fixed: toast kind `ok` is not a valid kind (`success`). |

## Fixed

1. **RESPONSE_FIELD, `views/agent.js`**: `POST agent/tasks` returns `202 { task_id, state, events_url }`. The view read `task.id`, so after submitting it navigated to `#/tasks/undefined`. Now reads `task.task_id`.
2. **RESPONSE_FIELD, `views/situation.js`**: shelter rows from `GET logistics/shelters` use `latitude`, `longitude`, `capacity_people`. The view read `lat`, `lon`, `capacity`, so no shelter ever had coordinates (no map marker, "(no coordinates)" in the table, capacity shown as a dash). Now reads the server names, with the old names kept as fallbacks.
3. **RESPONSE_FIELD, `views/audit.js`**: `POST audit/verify` returns `{ valid, checked, first_bad_id }`. The verdict read `broken_at`, so the "First broken record" line never appeared. Now reads `first_bad_id`.
4. **RESPONSE_FIELD, `views/hazards.js`**: the flood pack returns `road_blocked_candidates` and the tsunami pack returns `watch_candidates` as integer counts. The view only rendered these when they were arrays, so the panels never appeared. Counts now render as a number panel; arrays still render as tables.
5. **UI consistency, `views/alerts.js`**: acknowledge toast used kind `ok`. Changed to `success`.

## Pending and error states

Every view that starts with a spinner has a catch branch that replaces it with an error state, an alert, or an empty state. No spinner-forever case was found. Checked: admin-users, agent, alerts, artifacts, audit, datasets, hazards, logistics, missions, planning, public-warnings, reports, resources, simulation, situation, task (including the code-load button), and login/reset.

## Known gaps (not fixed, by design or outside scope)

- Offline decisions with no content hash. `missions.js` and `reports.js` enqueue `MISSION_DECISION` / `REPORT_DECISION` with `content_sha256: null` when the record has no hash. The sync schema requires a 64-hex hash, so the server rejects the item permanently. This is a frontend edge case; the fix is to refuse to queue without a hash. Not changed (behaviour decision).
- `simulation.js` never enqueues `SIMULATION_CREATE` (the outbox kind and the `sync` handler exist). Scenario runs are online-only. Not a mismatch; noted.
- `views/command-center.js` (not my file): all of its routes exist and no suspect field names were found by search. Its field reads were not audited line by line.

## Needs backend

No `MISSING_ENDPOINT` findings. Backend routes with no frontend screen (informational, not a contract break):

- `POST /api/warnings`, `GET /api/warnings`, `POST /api/warnings/{id}/publish`, `POST /api/warnings/{id}/withdraw`: no authoring UI. Only `GET /api/public/warnings` is used.
- `POST /api/datasets/{id}/reject`: no reject button in `datasets.js`.
- `POST /api/admin/users`: no create-account form (the page says accounts are created from the command line).
- `GET/POST/DELETE /api/admin/api-keys`: no UI.
- `POST /api/auth/password` (change own password): no UI.
- `GET /api/agent/tasks/{id}/events`: used by `task.js` through `EventSource`. Not a gap.
