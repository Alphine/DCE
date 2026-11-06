# DCE frontend

Vanilla HTML, CSS and ES modules. No build step, no framework.

**How it is served.** The FastAPI backend serves this folder at `/` when `DCE_SERVE_FRONTEND=true` (`DCE_FRONTEND_DIR` defaults to `../frontend`). All API calls use relative URLs such as `api/agent/tasks`, so the app works at `/` and under a sub-path. Open it through the backend, not from `file://`, because the session cookie and `/api` need the same origin.

**How to run with the backend.**
1. Start the backend with `DCE_SERVE_FRONTEND=true` and seed the demo accounts (`python -m app.seed`, password from `DCE_SEED_PASSWORD`).
2. Open `http://localhost:8000/` and sign in with a seeded account (admin, analyst, reviewer, approver).
3. For hash verification in the browser, use `localhost` or HTTPS. Web Crypto is not available on plain `http://` with an IP address.

**CDN dependencies** (loaded in `index.html`, no bundled copies):
- Chart.js 4.4.1: `cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js` (depth chart)
- Google Fonts: Chakra Petch, Inter, JetBrains Mono

The CDN scripts have no Subresource Integrity hashes yet. Pin them before the public demo.

**Layout.** `index.html` is the shell. `css/app.css` holds tokens, layout and components. `js/app.js` bootstraps the session, the nav and the role-gated routes. `js/api.js` is the fetch wrapper. `js/views/*.js` has one file per screen. `js/components/*.js` has the reusable pieces: stepper, badges, toasts, log terminal, world map (`world-map.js`, projection in `geo.js`), chart, hash check. `assets/` has the favicon, the logo and `world-map.svg`, a simplified copy of the MIT-licensed world-map-data outlines (Stephan Wagner). Rebuild it with `python scripts/build_world_map.py`.

**Checks.** `node --check` on every module passes. Behaviour has not been tested against a running backend.
