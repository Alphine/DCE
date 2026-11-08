# W2: logistics registry and coverage (SDD 15.1, 14.2)

Owner: agent W2. Branch feature/offline-global.

## Files

| File | State | What it does |
| --- | --- | --- |
| backend/app/database/migrations/0011_logistics.sql | new | Tables shelters, supply_items, teams, vehicles, with CHECK constraints |
| backend/app/routes/logistics.py | new | Routes under /api/logistics and the coverage() helper |
| backend/app/routes/planning.py | edited | Adds the "coverage" key to GET /api/planning/allocation. Other fields unchanged |
| backend/tests/test_logistics_api.py | new | 28 tests: roles, validation, filters, row cap, ordering, audit, coverage arithmetic |
| frontend/js/views/logistics.js | new | Four lists in tabs, filters, add forms and status change for Analysts |
| frontend/js/views/resources.js | edited | Estimate form unchanged, moved into a slot. New Coverage section (all roles) |
| docs/notes/w2-logistics.md | new | This file |

## Endpoints

- GET /api/logistics/shelters, /supplies, /teams, /vehicles. Viewer and above. Optional `country` (ISO 3166-1
  alpha-2) and `district` (case-insensitive). Max 500 rows, newest first.
- POST /api/logistics/shelters, /teams, /vehicles. Analyst and above. Returns 201.
- PATCH /api/logistics/shelters/{id}, /teams/{id}, /vehicles/{id}. Analyst and above. Send at least one field.
- POST /api/logistics/supplies. Analyst and above. Upserts by (shelter_id, item). Returns 201.
- GET /api/planning/allocation. Same as before, plus `coverage`: a list per allocated district with `need`,
  `capacity` (shelter_people, vehicle_people, total_people), `people_gap`, `stock` (per item), `teams_available`
  and `gaps` (items where stock < need, with `shortfall`). Empty list when the registry is empty.

Every write appends one audit row in the same transaction (actions shelter.created, shelter.updated, team.created,
team.updated, vehicle.created, vehicle.updated, supply.upserted). Details hold only field values that the
client sent. Responses have `created_by: {"id": ...}` and never a username.

## Requests for other files (not done by W2)

1. backend/app/main.py: add `logistics` to the import from app.routes, and add `api.include_router(logistics.router)`
   next to the planning line. Until this is done, the tests mount the router themselves (fixture `lenv` in
   test_logistics_api.py). The fixture skips this when the routes already exist, so it still works after the change.
2. frontend/js/app.js: add a route. The view is not registered yet:
   `{ name: 'logistics', title: 'Logistics', minRole: 'Viewer', match: (p) => (p[0] === 'logistics' ? {} : null), load: () => import('./views/logistics.js') }`
   and a nav entry `{ route: 'logistics', label: 'Logistics', href: '#/logistics', icon: 'logistics', minRole: 'Viewer' }`.
   Check that the icon name exists in frontend/js/components/icons.js, or pick an existing one.
3. Optional: if the service worker (frontend/sw.js) keeps a precache list of view modules, add
   frontend/js/views/logistics.js there.

## Design choices and limits

- Coverage matches districts by case-insensitive name across all countries. The planner has no country input, so two
  countries with the same district name would be merged. Use distinct district names until planning gets a country filter.
- Stock counts supply at shelters that are not CLOSED. Supply rows without a shelter have no district and are not counted.
- Capacity counts OPEN shelters and AVAILABLE vehicles only. Teams are reported as counts and do not affect gaps.
- Medical kits have no need figure in the flood pack, so they are reported in stock but never in gaps.
- Coverage reads the registry at request time, not the state when the simulation ran.
- Supply filters (country, district) go through the shelter. Stock without a shelter is excluded when a filter is set.
- Latitude and longitude are stored and validated but are not shown in the UI yet.

## Verification

`cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_logistics_api.py tests/test_planning_api.py -p no:warnings -o addopts="" -q`
gives 35 passed. The frontend views pass a syntax check with Node. No browser test was run.
