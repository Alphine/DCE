# Datasets screen (agent DATASETS)

## What changed

- `frontend/js/views/datasets.js` (edited): the Datasets screen.
  - Upload (Analyst+): display name, optional two-letter country code (sent as `country_code`), drag and drop or
    file picker. Accepts CSV and GeoJSON (`.csv`, `.geojson`, `.json`), up to 10 MB. Client checks are a convenience;
    the server checks again.
  - List: name, file, kind (CSV or GeoJSON), country, size, status badge, uploader, date. Status filter (client side).
  - Detail: status, data class (RAW_REPORT), country, kind, owner, rows, columns, SHA-256 with copy button.
  - Approve and reject (Reviewer+, not the uploader; two-step confirm). Reject takes an optional note (max 500).
    Only shown while the dataset is PENDING_VALIDATION. Other users see a role message.
  - Profile table with null counts and null share per column.
  - Preview: first 5 rows from the profile.
  - Map preview: shown only when the profile has `lat` and `lon` columns. Up to 1000 rows are placed on a local
    plane (SVG, points only, no base map, so no network). Rows with missing coordinates are skipped and counted.
    Approved datasets, or the uploader's own, only (the rows endpoint refuses others).
  - Used by: simulation runs and missions whose source is this dataset (from the newest-100 simulation list and the
    mission list), and a link to Hazard Intelligence with `?dataset=<id>`. Hazard results are computed on request
    and have no list endpoint, so the link is the only way to reach them.
- `frontend/css/datasets.css` (new): styles for the new parts. Uses tokens from `app.css`. Includes a reduced-motion rule.
- `docs/notes/datasets.md` (new): this note.

## Endpoints used

- `GET /api/datasets` (list, Viewer)
- `POST /api/datasets` (multipart: `file`, optional `name`, `country_code`; Analyst)
- `GET /api/datasets/{id}` (detail with profile)
- `GET /api/datasets/{id}/rows?limit=1000&offset=0` (map; approved or owner only)
- `POST /api/datasets/{id}/approve` (no body)
- `POST /api/datasets/{id}/reject` (optional JSON `{"note": "..."}`, max 500)
- `GET /api/simulations` and `GET /api/missions` (usage; Viewer)

Note: `docs/api.md` does not yet list `POST /api/datasets/{id}/reject`, `kind`, or `country_code` on
datasets. The backend implements them (`backend/app/routes/datasets.py`). The docs owner should add them.

## Requests for the owner

1. Add `<link rel="stylesheet" href="css/datasets.css">` to `frontend/index.html`, after `polish.css`.
2. Add `'css/datasets.css'` to the precache list in `frontend/sw.js` (next to `css/polish.css`).
   `js/views/datasets.js` is already precached there, so the new code ships with the same entry. Bump the cache version.
3. Optional: list the reject endpoint and the dataset `kind` and `country_code` fields in `docs/api.md`.

## Verification

- `node --check` on a copy of `datasets.js` passes.
- Against the local server (127.0.0.1:8010, analyst login): `GET /api/datasets`, `GET /api/datasets/{id}`,
  `GET /api/datasets/{id}/rows`, `GET /api/simulations` and `GET /api/missions` return the shapes the view reads.
  The pure helpers (`planarPoints`, `nullShare`, `usageFor`, `validateCountry`, `validateDatasetFile`) were
  run in Node on that data: 38 of 40 rows placed (2 have null lat), 2 simulations and 1 mission found for the
  seeded Jakarta dataset.
- Not verified in a browser. The upload, approve and reject flows were not exercised on the server.
