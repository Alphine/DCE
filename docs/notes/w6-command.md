# W6: Command Center decision queue

## Files

- `frontend/js/components/decision-queue.js` (new): queue model (`buildQueue`), wait formatting (`formatWait`, `waitMs`), role mapping (`deciderFor`), and the DOM panel (`decisionQueuePanel`). All DOM uses `h()`.
- `frontend/js/views/command-center.js`: queue panel above the existing grid, `loadQueue()` with `Promise.allSettled`, called from `load()`.
- `frontend/css/app.css`: appended under "Decision queue".

## Behaviour

- Sources: `GET missions?limit=500` (PROPOSED), `GET reports?limit=500` (OBSERVATION), `GET datasets` (PENDING_VALIDATION), `GET agent/tasks` (AWAITING_APPROVAL = gate A, decider Approver; AWAITING_REVIEW = gate B, decider Reviewer). Status filters are applied on the client.
- Deciders: mission = Approver; report and dataset = Reviewer; task = gate role. Visible to a viewer: items whose decider role passes `hasRole()`, plus the viewer's own items (marked "Waiting for another person", no link).
- Per type: oldest first, at most 10 items (decidable first, then own), with "View all" and "more" links.
- KPI tiles: waiting count per type (with "to decide" and "yours"), and the oldest wait.
- Failed request: that group shows a warning; the other groups still render.
- Empty state: "Nothing is waiting for a decision."
- The existing tiles, recent tasks, map, chart and assistant remain below the queue.

## Known limits and choices

- Agent tasks have no `country_code` in the contract, so they show `ID` by the fallback rule. Ask the backend owner if tasks should carry a country.
- Task waits use `updated_at` (closest to when the task entered its gate). Other items use `created_at`.
- Waits are measured at load time. The queue does not tick; Refresh updates it.
- `GET /api/alerts` is not used. The queue does not depend on it.
- The queue repeats the `agent/tasks` and `datasets` calls the page already makes. This is a small cost; merging them is a possible follow-up.

## Checks run

- `node --check` on both changed JS files (copied to .mjs).
- Node tests in a scratch folder outside the repo: wait formatting, role mapping, sorting, own split, per-type cap, failed-source handling.
- Render check with a minimal `document` stub: panel text, notices, links, no `innerHTML`.
- Not done: real browser run against the backend.
