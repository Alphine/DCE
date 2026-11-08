# Mini charts (agent CHARTS)

## What changed

- `frontend/js/components/mini-charts.js` (new): pure helpers (`num`, `clamp`, `barShare`, `barShares`,
  `gaugeState`, `coveragePercent`, `sparklinePoints`, `pointsAttr`, `toneClass`, `fmtNum`) and builders
  (`sparkline`, `barRow`, `gauge`, `tableFallback`). SVG uses `createElementNS`, HTML uses `h()`. No innerHTML.
- `frontend/css/charts.css` (new): layout and colors for the builders. Colors come from tokens with fallbacks.
- `frontend/js/components/timeseries.js`: two sparklines (all reports, verified) and a `<details>` table.
  The export `timeseriesChart(data, {title})` is unchanged, so `alerts.js` still works.
- `frontend/js/views/alerts.js`: severity counts as bar rows above the list (chart area only).
- `frontend/js/views/logistics.js`: supply stock summary (bars per item and a coverage gauge), supplies tab only.
- `frontend/js/views/resources.js`: Coverage section shows district cards (gauge and stock-against-need bars).
  The table moved into a `<details>`. Estimate and gap code are unchanged.

## Requests for the owner

1. Load `frontend/css/charts.css` from `index.html` (or the CSS bundle). Without it the charts render unstyled.
2. Define tokens in `frontend/css/command.css`: `--sev-low`, `--sev-medium`, `--sev-high`, `--sev-critical`
   (the classes `sev-*` use them), and optionally `--chart-line`, `--chart-verified`, `--chart-fill`, `--chart-track`, `--line`.
3. `frontend/css/app.css` still has `.ts-svg`, `.ts-line`, `.ts-dot`, `.ts-grid`, `.ts-axis`, `.ts-legend` and `.ts-swatch`
   rules from the old chart. They are now unused and can be removed.
4. Logistics has no per-item need. The supply summary scales bars to the largest stock and says "Need is not shown here".
   A true stock-against-need view needs need per item, for example from the planning allocation endpoint.
   Owner decision: whether the logistics screen should fetch it.
5. Tone colors: a coverage gap uses HIGH, and covered uses LOW. Confirm that LOW reads as "fine" in `command.css`.

## Tests

- Node tests of the pure helpers (12 cases: scaling, clamping, NaN handling, sparkline coordinates, tone mapping)
  live in the scratchpad, outside the repo.
- Builders were not run in a browser. Check the Alerts, Logistics and Resources screens visually after `charts.css` is loaded.
