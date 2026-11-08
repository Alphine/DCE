# W4: alerts and report time series

Status: backend and tests done. Frontend views written and syntax-checked, not yet run in a browser.
Wiring into `main.py` and `app.js` is still needed (see requests below).

## What was built

| File | Purpose |
| --- | --- |
| `backend/app/database/migrations/0012_alerts.sql` | `alerts` table, indexes on `created_at` and `(country_code, created_at)` |
| `backend/app/alerts.py` | Pure builders (`report_verified_alert`, `threshold_crossings`, `sync_rejected_alert`) and write helpers that run inside the caller's transaction |
| `backend/app/routes/reports.py` | One import line and one call, `alerts_core.write_report_verified(conn, row, target)`, inside `apply_review`. The sync path and the direct route both go through `apply_review`, so both create the alert |
| `backend/app/routes/alerts.py` | `GET /api/alerts`, `POST /api/alerts/{id}/acknowledge`, `GET /api/alerts/summary`, `GET /api/timeseries` |
| `backend/tests/test_alerts_api.py` | 20 tests: generation, acknowledge, filters, summary, time series, privacy, pure functions |
| `frontend/js/views/alerts.js` | Summary tiles, filtered list with Acknowledge buttons, intake chart |
| `frontend/js/components/timeseries.js` | Inline SVG line chart (createElementNS) with a table fallback in a `<details>` |
| `frontend/css/app.css` | Appended under "Alerts and time series" |

## Rules

- **Generation.** REPORT_VERIFIED is written only when a report becomes `VERIFIED_OBSERVATION`. Severity is the
  report's `severity_reported`, or MEDIUM when absent. The country is the report's country, with NULL shown and
  stored as `ID`. A rejected report writes nothing.
- **Titles and detail.** Titles are capped at 120 characters. `detail_json` holds ids, hazard type, the
  free-text location name, and counts. It never holds a username.
- **Acknowledge.** Reviewer or higher. Idempotent: the first call sets `acknowledged_by` (user id) and
  `acknowledged_at` and writes one `alert.acknowledged` audit row. Later calls return 200 unchanged, with no
  second audit row. Unknown id returns 404.
- **List.** Viewer. Newest first, default limit 50, max 200. Filters: `country`, `kind`, `severity`,
  `unacknowledged=true`.
- **Summary.** Viewer. `by_severity` and `by_kind` count unacknowledged stored alerts. `DECISION_WAITING` is never
  stored. It is computed from PROPOSED missions plus OBSERVATION reports, and counted only for Analyst and above,
  because Viewers may not see those rows. `total` equals the sum of `by_kind`.
- **Time series.** Viewer. `hours` must be 24, 72 or 168. Buckets are UTC hours ending at the current hour, with
  zeros for empty hours. Reports are placed by `created_at`. Viewers see verified reports only, so their `reports`
  count equals their `verified` count. `by_hazard` lists all seven hazard types, zero-filled.
- **THRESHOLD_CROSSED.** Pure function `threshold_crossings(before, after, thresholds, dataset_id=...)`, fires when
  `before <= threshold < after`. It is tested only. The hazard engine does not call it on requests.
- **SYNC_REJECTED.** Helper `write_sync_rejected(...)` exists. Nothing calls it yet.

## Requests for other files (not edited by W4)

1. **`backend/app/main.py`** (owner). Add `alerts` to the `from app.routes import (...)` list and add
   `api.include_router(alerts.router)` next to the other includes, before the `/{rest:path}` catch-all.
   Until this is done, `/api/alerts` and `/api/timeseries` return 404 in the running app. The tests do not depend
   on it: `tests/test_alerts_api.py` serves the same router through a wrapper app.
2. **`frontend/js/app.js`** (owner). Add a route and a nav entry:
   - route: `{ name: 'alerts', title: 'Alerts', minRole: 'Viewer', match: (p) => (p[0] === 'alerts' ? {} : null), load: () => import('./views/alerts.js') }`, path `#/alerts`
   - nav item: `{ route: 'alerts', label: 'Alerts', href: '#/alerts', icon: 'alerts', minRole: 'Viewer' }`. Add an `alerts` icon in `components/icons.js` or pick an existing one.
3. **`backend/app/routes/sync.py`** (owner of sync). When a queued item is rejected, call
   `alerts_core.write_sync_rejected(conn, op_id=..., item_kind=..., reason_code=..., country_code=...)` inside the
   same transaction that records the REJECTED sync op. The helper takes a reason code, not free text.
4. **Hazard engine** (owner of hazards). Call `threshold_crossings` when a dataset's hazard counts are computed,
   store the results with `write_alert`, and set a threshold configuration. This is a later stage.
5. **`docs/api.md`** (docs owner). Add rows for the four endpoints listed above.

## Migration numbering

0011 (logistics) and 0013 (warnings) exist from other work. 0012 is this migration. The runner accepts gaps.

## Not verified

- Frontend rendering in a browser (only `node --check` on both modules).
- Timezone edge cases at an hour boundary. The time series test sets `created_at` explicitly, but the route
  reads the clock once per request.
