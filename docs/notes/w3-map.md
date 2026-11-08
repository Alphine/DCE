# W3 notes: Leaflet situation map

## What changed

- `frontend/vendor/leaflet/`: Leaflet 1.9.4 (`leaflet.js`, `leaflet.css`, `images/` with the five PNGs, `LICENSE` = BSD 2-Clause), fetched from `https://unpkg.com/leaflet@1.9.4/dist/`.
- `frontend/data/geo/countries-110m.geojson`: country outlines (see source below). 253,743 bytes (under 1 MB). Only `name` and `iso2` properties are kept, to keep it small.
- `frontend/js/components/leaflet-map.js` (new): `createLeafletMap(container, { points, layers, country, onSelect, label })`. Resolves to a controller with `select(id)`, `clearSelection()`, `setLayer(name, on)`, `setCountry(code)`, `setPoints(points)` and `destroy()` (calls `map.remove()`). Also exports pure helpers `filterPoints`, `countryCodes`, `layerForPoint`, `normalizeCountry`, `isMappable`.
- `frontend/js/views/situation.js`: uses the new component. Adds layer checkboxes, a country select, a shelter layer (hidden on 404), and a table that shows the same filtered points as the map. Row labels are buttons that select the point on the map.
- `frontend/css/app.css`: appended block under the heading "Leaflet map" only.
- `frontend/js/components/world-map.js` is unchanged. `command-center.js` still uses it.

## Layers

Point layers come from `kind`: `REPORT` and `DATASET_ROW` go to `disaster`, `SHELTER` to `shelters`, `AFFECTED` to `affected`. `countries` is the outline layer. There is no tile layer, so the map makes no online tile requests.

## Map data source and licence

- Source: Natural Earth 110m admin-0 countries, `ne_110m_admin_0_countries.geojson`, from `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson` (fetched 2026-11-08).
- Licence: public domain (https://www.naturalearthdata.com/about/terms-of-use/). Attribution is not required; the map adds a credit line anyway.
- This replaces the outlines used by `assets/world-map.svg`, which `docs/map-data-licence.md` flags as unresolved. That file is still used by `command-center.js` through `world-map.js`, so it is not removed here.

## precache (for sw.js owner; do NOT edit sw.js here)

Add these paths to the `SHELL` array (relative to `frontend/`), and bump `CACHE_VERSION` because the SHELL list changes:

- `vendor/leaflet/leaflet.js`
- `vendor/leaflet/leaflet.css`
- `vendor/leaflet/LICENSE`
- `vendor/leaflet/images/layers.png`
- `vendor/leaflet/images/layers-2x.png`
- `vendor/leaflet/images/marker-icon.png`
- `vendor/leaflet/images/marker-icon-2x.png`
- `vendor/leaflet/images/marker-shadow.png`
- `data/geo/countries-110m.geojson`
- `js/components/leaflet-map.js`

`js/views/situation.js` and `css/app.css` are already listed.

## Requests for other owners

1. Backend `GET /api/situation`: add `country_code` to each point (reports already store it; dataset rows may use the dataset's `country_code`). Without it the country filter hides every point, and the select is disabled.
2. Backend `GET /api/logistics/shelters` (owner: other agent): the view expects a JSON array, or `{ shelters: [...] }` / `{ items: [...] }`, with `id`, `name`, `lat`, `lon` and optionally `country_code`, `capacity`, `status`. A 404 hides the layer. Any other error shows a warning.
3. `AFFECTED` points are not produced by any endpoint yet. The layer is wired but empty.

## Accessibility

- The map region has `role="region"` and an `aria-label`. Leaflet keyboard panning and zoom buttons remain.
- The table lists the same filtered points as the map, with a live count, and a keyboard-operable label button for each point with coordinates.

## Checks run

- `node --check` on copies in the scratchpad (`leaflet-map.mjs`, `situation.mjs`) and on `vendor/leaflet/leaflet.js`: pass.
- Node test of the pure helpers (layer mapping, layer and country filtering, country codes, coordinate checks): all assertions pass. The test file is outside the repo.

## Not verified

- No browser run. The Situation page needs the backend and a login, so the rendered map, the CSS and the console were not checked.
- Offline behaviour (service worker precache) is not tested, because sw.js is not edited here.
