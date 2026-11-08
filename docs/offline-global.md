# Offline-first and global scope (design, v0.1)

Status: agreed scope from the owner, 2026-11-08. This file is the contract for the three workstreams below.
Ownership is disjoint so the workstreams can run in parallel: backend (`backend/`, `docs/api.md`), PWA
(`frontend/`), and Tauri (`src-tauri/`, root `package.json`, `scripts/`).

## 1. Scope decisions

| Question | Decision |
| --- | --- |
| Offline scope | Full: reads, report intake, missions, and approvals work offline. Offline writes are queued in an outbox and sent on sync. |
| Meaning of "global" | Disasters and response across countries, not only Indonesia. Every report, dataset, mission, and simulation carries a country. Maps and rule packs are not tied to one country. |
| Tauri target | Windows desktop (`.msi` and `.exe` installers). Mobile comes later. |

## 2. Governance rules that offline mode must keep

- An approval or rejection made offline is a **pending decision**. It is not effective until the server accepts it.
- The server accepts a pending decision only if all of these hold, checked at sync time:
  1. The user still exists, is active, and has the role the decision needs (Approver for missions, Reviewer for reports and datasets).
  2. The item is still in the state the decision was made against (`PROPOSED` for missions, `OBSERVATION` for reports).
  3. The content hash the user saw equals the server's current content hash.
  4. The decider is not the proposer or submitter.
  5. The decision was made no more than 72 hours before sync. Older decisions are rejected and the user must decide again.
- A rejected pending decision stays in the outbox with a reason until the user dismisses it. It is never applied silently.
- Each accepted offline decision is audited with the original time (`decided_offline_at`) and the sync time.
- Offline sign-in is not allowed. The app keeps a read-only cache for a signed-in user whose session was valid
  at the last online check. Writes need a live session at sync time. If the session has expired, the outbox waits
  until the user signs in again. Nothing is lost.
- Sandbox runs, agent tasks, and dataset file uploads are **online only**. They are not queued.

## 3. Country model

- New migration adds `country_code TEXT` (ISO 3166-1 alpha-2, uppercase, validated against a bundled list) to:
  `reports`, `datasets`, `missions`, `simulation_runs`. Nullable for existing rows, which are treated as `ID`.
- Requests can filter by country: `?country=PH`. Responses include `country_code`.
- The world map and situation view can filter by country. Rule packs keep their hashes and are labelled
  illustrative, and a pack may declare the countries it was written for (`countries: []` means any).
- The sample data stays as it is. New sample datasets for at least two other countries are added for tests.

## 4. Sync contract (backend)

`POST /api/sync/batch` (session cookie only, Analyst or higher for intake, role-checked per item)

Request:
```json
{"client_id": "device uuid", "items": [
  {"op_id": "uuid, unique per item", "kind": "REPORT_CREATE", "payload": {...}, "made_at": "ISO-8601 UTC"},
  {"op_id": "uuid", "kind": "MISSION_DECISION", "payload": {"mission_id": "...", "decision": "approve", "content_sha256": "...", "note": null}, "made_at": "..."}
]}
```

Response: one result per item, in the same order:
`{"op_id": "...", "status": "APPLIED" | "DUPLICATE" | "REJECTED", "code": "...", "message": "..."}`

Rules:
- `op_id` is idempotent. Replaying a batch returns `DUPLICATE` and changes nothing.
- Each item is applied in its own transaction. One rejected item does not block the others.
- Kinds: `REPORT_CREATE`, `REPORT_DECISION`, `MISSION_PROPOSE`, `MISSION_DECISION`, `SIMULATION_CREATE`.
- `SIMULATION_CREATE` is accepted only if the dataset is approved and the pack hash matches.
- Limit: 200 items and 1 MB per batch.

Read endpoints used by the cache: `GET /api/sync/snapshot?country=` returns the list data a viewer may read
(verified reports, approved datasets metadata, missions, latest simulation runs) with an `etag` per section.
The PWA stores it and refreshes it when online.

## 5. PWA (frontend)

- `manifest.webmanifest` with name "Disaster Commander Edge", icons, `display: standalone`.
- `sw.js` (service worker): caches the app shell (all files under `frontend/`), uses network-first for `/api/*`
  and falls back to the IndexedDB cache. It never caches `/api/auth/*` responses.
- IndexedDB stores: `snapshot` (per section), `outbox` (pending ops with `op_id`, `kind`, `payload`, `made_at`,
  `status`, `last_error`), and `session_meta` (user id, role, email, last online check).
- Sync manager: runs on `online`, on app start, and every 60 seconds while online. It sends the outbox in batches
  of up to 200 items and updates each item from the server result.
- UI: a persistent status line (Online / Offline / N pending / N rejected). A "Pending" list shows each queued
  decision and any rejection reason, with a Dismiss action for rejected items.
- Every screen that writes shows "Saved offline, will send when online" when the request is queued, not "Saved".

## 6. Tauri (desktop)

- `src-tauri/` with Tauri 2. The window loads `https://commander.basyid.dev`, the same origin as the API.
  This is required: the session cookie is `SameSite=strict`, so a page served from `tauri://localhost` could not
  send it to the API. Because it is the same origin, the service worker (section 5) caches the shell, and the app
  works offline after the first successful online start.
- The first launch needs the network once. Offline cold start (no cached shell) is out of scope for this stage.
- Build: `npm run tauri build` on Windows, producing an NSIS `.exe` and an `.msi`.
- Requires Visual Studio Build Tools (MSVC) and WebView2. Both are present on the owner's laptop.
- Code signing is not included in this stage. The installer will show an unknown-publisher warning.

## 7. Acceptance for this stage

- Backend: the full suite passes. New tests cover idempotent replay, per-item isolation, the five governance checks,
  country validation and filters, and the 72-hour rule.
- PWA: the app shell loads offline. A report created offline is sent after the network returns. A decision made
  offline stays pending until sync and is shown as rejected if a governance check fails.
- Tauri: an installer is built, and the app opens and shows the cached data with the network off.
