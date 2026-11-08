# Landing page merged into the app root

The public landing page is now part of the app at the site root. One URL serves both audiences.

## Files

- `frontend/js/views/landing.js` (new): the landing view, built with `h()` and `svg()` from `frontend/js/dom.js`. Includes the English / Bahasa Indonesia dictionary (same text as the former `welcome.js`) and the EN / ID switch. The choice is stored under `dce-welcome-lang`, as before.
- `frontend/css/landing.css` (new): the former `welcome.css`, with every selector scoped under `.landing`. Keyframes are renamed `landing-*`. Reduced motion stops all decorative animation.
- `frontend/js/app.js`: route rules below.
- `frontend/js/views/about.js`: new "What this is" and "Try it" panels at the top. The two diagrams are now built with `svg()` instead of `innerHTML`. Every panel renders without a session.
- `frontend/js/dom.js`: adds `svg()`, the namespace-aware twin of `h()`. `h()` itself is unchanged in behaviour.
- `frontend/index.html`: links `css/landing.css` after `css/sandbox.css`.
- `frontend/welcome/index.html`: now only a meta refresh to `/` and a plain link to `/`. No script. `welcome.css` and `welcome.js` are no longer referenced and can be deleted later.
- `frontend/sw.js`: cache `dce-shell-v13`; precaches `js/views/landing.js` and `css/landing.css`.

## Route rules

| Route | Visitor (not signed in) | Signed-in user, or demo sandbox |
|---|---|---|
| `#/` or no hash, `#/dashboard` (command) | Landing page. The header stays hidden; the landing has its own top bar with a sign-in link. | Command Center |
| `#/login`, `#/reset`, `#/public`, `#/about` | Shown. These routes are in `PUBLIC_ROUTES` and skip the `minRole` check. | Shown |
| `#/login` while signed in | Not applicable | Redirects to `#/` |
| Any other route | Redirects to `#/login` | Shown if the role allows it, otherwise "Not available for your role" |

The demo sandbox signs in as a demo user (`auth/me` returns it), so it follows the signed-in column.

Landing links use `#/login`, `#/public` and `#/about`. In-page section links scroll with JavaScript and do not change the hash, because the router reads the hash.

## Checks

- `node --check` passes for `dom.js`, `app.js`, `about.js`, `landing.js` and `sw.js` (copied to `.mjs` first).
- Landing ids are unique and prefixed `landing-`. No `<script>`, no `innerHTML` in the landing or about views.

## Owner checks in Chrome

- Signed out at `/`: landing shows, no header, EN / ID switch works and survives reload.
- `/#/about` signed out: all panels render.
- `/welcome/`: redirects to `/`.
- Signed in at `/`: Command Center, unchanged.
