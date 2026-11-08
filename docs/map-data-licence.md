# Map data licence review: frontend/assets/world-map.svg

Status: finding for review. This is not legal advice.

**Update 2026-11-08: resolved by replacement.** `frontend/assets/world-map.svg` has been removed. The Situation and
Command Center maps now use Leaflet 1.9.4 (BSD 2-Clause, vendored in `frontend/vendor/leaflet/`) with Natural Earth
1:110m countries (public domain, `frontend/data/geo/countries-110m.geojson`). No online tiles are loaded. The
About page lists both sources. The MIT notice belonged to the removed asset, so the current map data is not MIT.
`frontend/js/components/world-map.js` still exists for its legend and point helpers; its SVG loader is no longer
used and should be removed in a later cleanup.

## What was checked

- Derived asset: `frontend/assets/world-map.svg` (about 1.2 MB, 435 country `<path>` elements, class `world-countries`).
- Build script: `scripts/build_world_map.py`. It simplifies the upstream `maps/world.svg` from `stephanwagner/world-map-data` (path quantising, Douglas-Peucker reduction, small-island removal, border lines dropped, styling moved to CSS). It keeps the upstream MIT licence text in the SVG header comment.
- Upstream README "Sources" section: Natural Earth Data, Wikipedia (Miller projection PDF on Wikimedia Commons), OpenStreetMap, Google Maps.

## Licence terms

1. **Upstream repository (MIT, Stephan Wagner, 2025).** Use, copy, modify, merge, publish, distribute and sell are permitted. The only condition is that the copyright and permission notice is included in all copies or substantial portions. The asset header already carries this notice, so this condition is met for the repo's own data. The upstream README makes no licence statement about its sources.
2. **Natural Earth.** Public domain. Attribution is not required (the site suggests citation lines). Some third-party datasets are licensed to Natural Earth only for base-map use, but none of those (Washington Post, JRC rivers and lakes, XNR roads, time zones) is an obvious element of a country outline layer.
3. **OpenStreetMap (ODbL).** Attribution is required ("Provide credit to OpenStreetMap by displaying our attribution notice", with a link to https://www.openstreetmap.org/copyright). If the outlines are derived from OSM, a Derivative Database must be shared under ODbL. A Produced Work (such as a rendered map image) needs attribution but not share-alike. The SVG is a derived vector database of geometry, so share-alike would likely apply to it. The exact boundary between Produced Work and Derivative Database was not confirmed from the fetched page; the full ODbL legal code is needed for that.
4. **Google Maps.** Third-party summaries of the Google Maps Platform terms restrict caching or storing Google Maps Content beyond temporary use, copying, creating derivative works from it, and bulk extraction. These are not Google's current official text. The official page was truncated when fetched, so the exact clauses could not be quoted. Google content should not be redistributed in this asset.

## Which parts of the derived SVG could be affected

- The country outline geometry (all 435 paths, the `world-countries` group). This is the only content in the file.
- The header comment and licence notice (no effect; it documents the MIT notice).
- The build script's simplification does not change the licence position of the geometry; it is still a derivative of the upstream data.

The main unknown is provenance. The upstream README says only that the maps were drawn in Adobe Illustrator "with the help of following public map material" and lists four sources. It does not say which source supplied the country outlines. The team needs to check that before deciding.

## Required actions if the asset is kept

- Keep the MIT notice in the header (already done).
- If any part traces to OpenStreetMap: add a visible attribution line (for example "Map data © OpenStreetMap contributors, ODbL") near the map in the UI, and treat the SVG as ODbL-licensed derived data (share-alike) for distribution purposes.
- If any part traces to Google Maps: that part must be removed.
- If Natural Earth only: a credit is good practice but not required.

## Recommendation

Replace the asset with a map built only from Natural Earth data (public domain), keep the upstream MIT notice in the header of any file still derived from that repo, and remove the OpenStreetMap and Google Maps dependency from the asset. Keeping the current file is acceptable only if the upstream author or repository confirms that the country outlines come solely from Natural Earth, and the attribution in the header is then sufficient. Adding an OpenStreetMap attribution line does not remove the share-alike concern if OSM data is in the outlines, so replacement is the safer path. Regardless of the choice, record the source and licence in the project before release.

## What could not be verified

- Which upstream source supplies the country outlines in `maps/world.svg`. The file was not downloaded in this review (the upstream file is about 13.6 MB and is not committed), so its per-country provenance was not checked.
- The exact text of Google's current Maps Platform terms (the official page was truncated when fetched). The restriction wording above comes from third-party summaries.
- The exact ODbL attribution string and the Produced Work vs Derivative Database boundary (the fetched OSM page defers to the full ODbL text).
- Whether the upstream MIT LICENSE text fetched from the `master` branch matches the `main` branch used by `build_world_map.py`. The build script's `LICENSE_URL` points at `main`; the fetch in this review used `master`.

## Sources

- https://raw.githubusercontent.com/stephanwagner/world-map-data/master/LICENSE
- https://github.com/stephanwagner/world-map-data
- https://www.naturalearthdata.com/about/terms-of-use/
- https://www.openstreetmap.org/copyright
- https://cloud.google.com/maps-platform/terms/maps-service-terms
