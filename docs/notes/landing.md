# Landing page: owner follow-ups

The public landing page lives at `frontend/welcome/` (`index.html`, `welcome.css`, `welcome.js`) and is served as `/welcome/`. It is static, with no build step. The files outside that folder were not changed.

## Changes needed outside frontend/welcome/

1. **Link from the login page.** Add a link to `/welcome/` on the login view (`frontend/js/views/login.js` or the login markup in the app), for example "What is this?". Without it, the page is reachable only by direct URL.
2. **Windows desktop release link.** The offline section says the desktop build is "published with the project releases", with no link. Add the GitHub releases URL once the repository location is known. No repository URL was found in the docs.
3. **About page access.** The landing page links to `/#/about`. `PUBLIC_ROUTES` in `frontend/js/app.js` is `login, reset, public`, so an anonymous visitor who clicks "Read the About page" is redirected to login. Either add `about` to `PUBLIC_ROUTES` (the About page shows only architecture text) or accept the redirect.
4. **Service worker.** Check `frontend/sw.js`: if it caches only the app shell, `/welcome/` should either be added to the precache list or left to the network. The page works without the service worker.
5. **Deployment.** Confirm the static host serves `frontend/welcome/index.html` at `/welcome/` (trailing slash). `docs/deployment.md` may need one line about it.
6. **Licence.** The footer reads "Licence: to be confirmed by the project owner". Replace it in `frontend/welcome/index.html` (footer) and in `frontend/welcome/welcome.js` (both `footer.licence` entries) once decided.
7. **Social preview.** There is no `og:image` yet. Add a 1200x630 image in `frontend/welcome/` and a matching `<meta property="og:image">` if link previews matter for judging.

## Notes on the page itself

- Links to the app use `/#/login`, `/#/public` and `/#/about`, which assume the app is served at the site root.
- Fonts come from the same Google Fonts URL the app uses (Chakra Petch, Inter, JetBrains Mono). No other external resources are loaded.
- Language switch: English is the default. Indonesian is chosen automatically if the browser language starts with `id`. The choice is stored in `localStorage` under `dce-welcome-lang`, inside a try/catch.
- Claims on the page should be checked against the code before the judging round, in particular: the hash-verified rule packs, the hash-chained audit log, the approval gates on plans and missions, the outbox behaviour, and the country filter on the map.
