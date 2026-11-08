# UX and visual audit: operator screens

Scope: `frontend/css/app.css`, `command.css`, `charts.css`, `empty.css`, the layout code in `views/command-center.js`, `situation.js`, `alerts.js`, `logistics.js`, `missions.js`, `reports.js`, and `components/leaflet-map.js`. Fixes are in `frontend/css/polish.css`. No other CSS or JS was changed (the two components named in the brief needed no markup change).

Verification key: **read** = checked by reading the rule and the markup that uses it. **visual** = needs the owner to look at it in a browser. No rendering was done in this pass.

## Summary

The app is not plain because of missing decoration. It looks flat for four reasons: the page structure has weak hierarchy (panel titles and KPI numbers are similar in weight), the map is sized in four places and is not the anchor, several controls are unstyled native controls, and hover, focus and empty states are too faint to notice.

---

## Problems, ordered by impact

### 1. Native controls outside `.field` are unstyled (forms, colour and contrast)

- **Where:** `alerts.js` lines 27-35 and 56-60 (`#al-country`, `#al-severity`, `#al-hours`, placed in `panel({ actions })`). `logistics.js` line 229 (status `select` in `.row`). `admin-users.js` lines 85-90 (role and status selects and email input inside the table). `lang-switch.js` (`.lang-switch__select`).
- **Why:** The only styled controls are `.field input/select/textarea` and `.input` (app.css, section 6). Nothing styles a bare `select` or `input`. Also `:root` has no `color-scheme`, so the native dropdown and its options can render light on the dark theme.
- **Change:** `polish.css` block 1. A zero-specificity `:where()` rule gives every text-like input, select and textarea the field look. Options get `--bg-1`. `color-scheme: dark` is set. Existing class rules still win.
- **Before:** browser default boxes in the alerts filter bar and admin table. **After:** same dark box as the rest of the app, with an amber focus ring.
- **Verified:** read. **Visual:** owner to check the alerts filter bar, admin users table, and the language dropdown opened on Windows.

### 2. The map is not the visual anchor, and its height is set in four conflicting places

- **Where:** `command.css` 108-125 (`.cc-hero .lm-map` with `!important`, `clamp(460px, 64vh, 640px)`, then 320px at 720). `app.css` `.lm-map` 360px. `app.css` `.situation-map .wm` 420px (dead: Situation draws a Leaflet map, `.wm` is never rendered there). `app.css` 640px rule 280px.
- **Why:** Map height changes at each breakpoint and differs between screens, so the map moves and looks smaller than the data needs. The map panel has the same border and shadow as every other panel, so nothing marks it as the main view.
- **Change:** `polish.css` block 5. On Command Center (720px and up) the map is `clamp(480px, 70vh, 680px)`, with a cyan top rule on its panel. Situation uses `.situation-map .lm-map` at `clamp(420px, 62vh, 600px)`, and 300px on phones. The dead `.wm` rule is left in place (owner may delete it; it does no harm).
- **Before:** about 460px map at 1280x720, sat under a toolbar and a legend. **After:** about 500px at 720px viewport height, and up to 680px on large screens.
- **Verified:** read (selector specificity checked: the new rules are either later in the cascade or more specific, and the phone override is outside the desktop query). **Visual:** owner to confirm the map height and that the zoom control and attribution still sit inside the frame.

### 3. Panel titles are weak and inconsistent (hierarchy)

- **Where:** `app.css` `h2` (0.95rem, uppercase, 0.12em tracking) for `.panel-title` in `panel()` (`dom.js` 80-89). `h3.panel-title` in `missions.js` 245, `reports.js` 249, `resources.js` 118-122, `simulation.js` 234-252, `hazards.js` 146 and `situation.js` 266 renders 1.05rem in sentence case. Two title styles on one app.
- **Why:** Small tracked caps read as captions. The same element name gives two sizes and cases.
- **Change:** `polish.css` block 3. One title style for `h2` and `h3`: Chakra Petch 1.05rem, sentence case, full text colour. Panel heads get a rule under them, so the title and body are separated.
- **Before:** tiny caps, 14px, mixed with 16px sentence case. **After:** one title size and case, with a divider.
- **Verified:** read. **Visual:** owner to check the panel headers on Command Center and Missions.

### 4. Page header has no separation from content (spacing)

- **Where:** `app.css` `.page-head` (margin-bottom 22px, no rule). Used by `pageHead()` in every view.
- **Change:** `polish.css` block 2. Bottom rule and 16px padding before the 22px gap. Subtitle at 14.5px with 1.5 line height.
- **Verified:** read. **Visual:** check that a two-line subtitle still wraps cleanly on phone.

### 5. KPI tiles: number does not dominate, label is faint (hierarchy and contrast)

- **Where:** `app.css` `.tile-value` (2rem), `.tile-label` (11px, `--text-3`). `.indicators .tile` padding 12px. `command.css` `.cc-stat-value` 26px, `.cc-stat-label` 11px.
- **Change:** `polish.css` block 4. Number `clamp(1.9rem, ..., 2.4rem)`, weight 700. Labels 12px and `--text-2`. Indicator tiles in the Command Center left column get their own clamp. The inference tile's text value keeps its smaller size (a specific rule restores it). Status bar number 30px.
- **Before:** a 2rem number at 600 weight, label near the background tone. **After:** the number is the first thing read in each tile.
- **Verified:** read. **Visual:** check the inference tile with "mock" and the quota tile "x/y" in the left column at 1280px width.

### 6. Tables: the hover row is invisible and the first column is weak

- **Where:** `app.css` `.table tbody tr:hover` = `rgba(255,255,255,.025)`, which is almost nothing on the dark background. First column in every table is a plain `td` (Situation's first column is "Kind", and the actual label is column 2 as a button).
- **Change:** `polish.css` block 6. Hover row uses `--cyan-soft` on every cell, with a 3px cyan bar on the first cell. First column is `--text` and 600 weight. Header 12px in `--text-2` on `--bg-1` (opaque, so the sticky header does not show rows through it). Phone padding tightened to 9px 10px.
- **Before:** hover barely visible; first column the same as every other column. **After:** hovered row is clear; first column is the one you read first.
- **Verified:** read. **Visual:** hover a row on Situation and Alerts. Note for owner: on Situation the first column is the Kind label, so it is now the bold one. If you prefer the Label column to be bold, that is a markup change in `situation.js` (reorder the cells), which was outside this pass.

### 7. Empty states look like body text, not like a state (empty states)

- **Where:** `empty.css` `.rich-empty` (padding only, no frame). `emptyState()` used inside panels (Command Center assistant, feed, map; Situation; Alerts).
- **Change:** `polish.css` block 9. A dashed frame for empty states inside panels, and the title in `--text`. Keeps the icon and action links unchanged.
- **Verified:** read. **Visual:** check the "No open items" and "No points yet" frames.

### 8. Hover and focus states missing or too faint

- **Where:** `.feed-row:hover` (3% white). `.assistant-link` (no hover). `.btn-link` in tables (hover shows the button tint instead of an underline). `.situation-layer` and `.wm-toggle` checkboxes (no focus ring, the browser default shows only on some browsers).
- **Change:** `polish.css` block 8. Feed rows 5%. Assistant links and table buttons underline on hover. Checkbox labels take the text colour on hover. Checkboxes get an amber accent and a focus ring.
- **Verified:** read. **Visual:** keyboard Tab through the Situation layer checkboxes.

### 9. Form labels are too quiet (forms)

- **Where:** `app.css` `.label` (13px, `--text-2`). Labels and hints are the same tone, so the hint and the label look equal.
- **Change:** `polish.css` block 7. Label in `--text` at 13.5px. Field gap 16px.
- **Verified:** read. **Visual:** check a form such as Reports.

### 10. Phone: touch targets and iOS zoom (mobile)

- **Where:** `.btn-sm` 32px, `.wm-toggle` 32px, `.situation-layer` (no height), inputs at 15px. Inputs under 16px make iOS Safari zoom on focus.
- **Change:** `polish.css` block 10, at 720px and below. Buttons 44px (small buttons 40px), inputs 44px and 16px, layer and toggle rows 40px, table cells 9px 10px, status value 24px.
- **Verified:** read. **Visual:** test on a phone-width emulation (360px): Command Center, Situation, Alerts.

### 11. Small text (typography)

- **Where:** `.step-state` 10.5px. `.sev-chip` 11px (fine). Mono labels at 11px in several places.
- **Change:** `.step-state` to 11px. Other mono labels left as they are.
- **Verified:** read.

### 12. Media overflow (mobile)

- **Change:** `polish.css` last block. `img, svg, canvas, video { max-width: 100% }`, so a wide SVG or canvas cannot force a horizontal page scroll. Tables keep their own scroll inside `.table-wrap`.
- **Verified:** read.

---

## Not changed (outside this pass)

- **Topbar height.** `app.css` `.topbar`, `.nav--tools` and the two-row nav use about 120px of a laptop screen and stay sticky. Shrinking the tools row to an icon row or hiding it under a menu would give the map more room. This is an app-shell decision for the owner.
- **Command Center order.** The status bar (four stat cards and two clocks, `command-center.js` `renderStatus`) sits above the map and pushes it down about 150px. Moving the status bar under the map would make the map the first thing, but changes the view structure, so it was not done here.
- **Situation first column.** See problem 6: the bold column is "Kind". Reordering the cells in `situation.js` `pointRow` would make Label the first column; that is a JS change.
- **Dead rule.** `app.css` `.situation-map .wm` (420px) targets a map that is not rendered on Situation. Safe to delete.

## Checks run

- `frontend/css/polish.css`: braces 56/56, parentheses 82/82.
- Every class named in `polish.css` that does not come from an existing CSS file was checked against the JS: `panel-title`, `tile-*`, `cc-stat-*`, `cc-hero`, `panel--map`, `wm-host`, `lm-map`, `situation-map`, `feed-row`, `assistant-link`, `btn-link`, `situation-layer`, `wm-toggle`, `step-state`, `rich-empty`, `empty-title`, `field`, `label`, `hint`, `btn`, `btn-sm`, `indicators` all appear in `frontend/js`.
- Colours: no new colour values. Only existing tokens (`--bg-1`, `--line`, `--line-strong`, `--text`, `--text-2`, `--cyan`, `--cyan-soft`, `--amber`, `--focus`, `--shadow`) and the one `rgba(255,255,255,.05)` hover tint already used by `.nav-item:hover`, and the `rgba(3,6,14,.7)` input fill already in `app.css`.
- Not run: any browser render, Lighthouse, or the test suite.

## Owner to verify visually

1. Command Center at 1280x720 and 1440x900: map height and framing, status bar numbers, KPI tiles.
2. Situation: map height, table hover row, first column, empty-state frame.
3. Alerts and admin users: native selects now dark, dropdown options readable.
4. Phone width (360px): bottom nav still clear of content, buttons and inputs at 44px, no horizontal scroll.
5. Panel headers on Missions and Reports (previously title case, now the same as the rest).
