# API audit (AUD-API)

Scope: backend HTTP behaviour against docs/api.md, exercised the way the UI does. Run against a local scratch
API (127.0.0.1:8011) on a scratch database outside the repo, seeded with `python -m app.seed`. The production VM
was not touched. Fixes are in `backend/app`, regression tests in `backend/tests/test_audit_regressions.py`.

## Flows exercised (smoke run, 208 calls, all matched the expected status)

| Flow | Result |
|---|---|
| Login as admin, analyst, reviewer, approver; viewer created by admin; wrong password 401; bad body 422 | pass |
| Upload flood, earthquake and wildfire CSV (analyst); self-approval refused; approve as reviewer | pass |
| Viewer upload and approve | 403, pass |
| Hazards for flood, tsunami, earthquake, wildfire packs; unknown pack 422; unknown dataset 404 | pass |
| Resource estimate (flood); earthquake pack 422; extra field 422; viewer 403 | pass |
| Simulations A and B, list, detail, limit violations 422, viewer 403, unknown run 404 | pass |
| Planning allocation (with and without a run) | pass |
| Reports: submit, list, detail, self-review 403, reject then re-review 409, verify | pass |
| Missions: propose from dataset and from report; self-approval 403; approve by approver; reject; double approve 409 | pass |
| Logistics: shelter create and patch, supplies upsert, team and vehicle create and patch, lists | pass |
| Alerts: list, summary, acknowledge (idempotent), viewer 403, timeseries 24/72/168, hours=48 422 | pass |
| Warnings: draft, HTML refused, creator publish 403, wrong hash 409, publish, republish 409, withdraw, public list without session | pass |
| Sync batch (mixed items, viewer, anonymous 401), snapshot | pass |
| Admin users: list, create, duplicate 409, patch role/email/disabled, self-disable 403, password set, API key create/list/use/revoke | pass |
| Role guards: 12 viewer write attempts | all 403 |
| Unauthenticated: 21 protected GETs and 10 POSTs | all 401 |

A second probe (about 190 edge-case calls: malformed JSON, out-of-range values, odd CSV content, sync items with
bad payloads, admin edge cases) found the two 500s below and no others. Several CSV and dataset edge cases
(BOM, CRLF, quoted newlines, NaN values, unicode districts) returned 200 or 422 as intended.

## 500s found and fixed

1. `POST /api/reports` with `observed_at` in the first hours of year 1 under a positive offset (for example
   `0001-01-01T00:00:00+14:00`). Converting to UTC overflowed. Also reachable through `POST /api/sync/batch`,
   where it would show as an `INTERNAL` item result. Fix: `routes/reports.py` `_observed_at` returns 422
   `VALIDATION_FAILED` ("observed_at is out of range.").
2. `GET /api/audit?offset=` with a value beyond SQLite's 64-bit range. Fix: `routes/governance.py` bounds the
   offset at 10^12, so the response is 422.

## Status and contract decisions

Fixed:
- `POST /api/admin/api-keys` with no body returned 422. Docs section 13 says the body is optional (default: the
  caller). Fix: body is optional. Now 201 with the caller as owner.
- `PATCH /api/admin/users/{id}` `disabled` accepted strings such as `"yes"`, `"off"`, `1` (Pydantic lax mode), and
  `"yes"` would disable an account. Docs say `true | false`. Fix: `StrictBool`, so these return 422.

Kept as is (documented here):
- `POST /api/datasets` over 10 MB returns 413 with code `VALIDATION_FAILED`. Docs give the limit but no status; 413
  is the accurate status. Keep.
- `source_reference` and `location_name` given as `""` are stored as null (`_clean_text`). This is the documented
  "unknown stays null" rule, so it is not a 422. Keep.
- `hours` given as a numeric string (`"24"`) is accepted (Pydantic lax coercion). Harmless. Keep.
- `DELETE /api/health` returns 404, not 405. The `/api/{rest:path}` catch-all answers every unknown method with the
  error envelope. Low impact. Not changed; a future change could map known paths to 405.
- Viewer `GET /api/audit` returns 403 and unauthenticated returns 401, as the role table says.
- A simulation with `hours=72` on a 40-row dataset is accepted (40 x 73 is far below the 1,000,000 cap). Correct.

## Usernames in responses

Verified: reports, simulations, warnings, alerts, logistics and situation responses carry ids only.

Not changed, needs an owner decision:
- `GET /api/missions`, `GET /api/missions/{id}`, and the mission sync snapshot include `proposer.username` and
  `decided_by.username`. Docs section 2 says "ids only" for reports, and the w5 and w2 notes say the same for
  warnings and logistics. Docs do not say it for missions. Removing the usernames would change what the frontend
  shows, so this was left alone.
- `GET /api/datasets` and agent-task `owner` include `username`. Docs section 3 shows that shape explicitly.
- The audit log `actor` is a username by design (reviewer-only, docs section 3 AuditRecord).

## Regression tests

`backend/tests/test_audit_regressions.py` (10 tests):
- observed_at before year 1 and after year 9999 in UTC returns 422 (HTTP and sync).
- Audit huge offset returns 422; normal paging still works.
- API key without a body, and with `{}`, is owned by the caller; unknown owner is 404.
- `disabled` must be a JSON boolean (`"yes"`, `1`, `"true"`, `"off"` return 422 and the account stays active);
  `true` and `false` still disable and enable.

## Scratch material

Smoke and probe scripts, logs, and results live in the session scratch folder, outside the repository.

## Suite result

Full backend suite after the fixes: 621 passed, 7 skipped (611 before this audit plus the 10 new regression tests).

The scratch API on 127.0.0.1:8011 was left running: stopping it was denied by the permission check, so it needs stopping by hand.
