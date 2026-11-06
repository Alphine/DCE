# Sample datasets

## flood_incidents_sample.csv

**This file is SYNTHETIC.** It was generated for demonstration and testing only. The 40 rows do not describe real flood events, real roads, or real populations. The district names are real Jakarta districts, but the values, timestamps, and coordinates are invented.

**Do not use this data for operational decisions**, disaster response, resource allocation, or public communication.

Columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | string | Synthetic incident ID (`INC-001` to `INC-040`) |
| `district` | string | Jakarta district name |
| `reported_at` | ISO 8601 UTC | Synthetic timestamp |
| `water_depth_cm` | integer | Empty means unknown |
| `road_blocked` | 0 or 1 | 1 means the road is blocked |
| `population_affected` | integer | Empty means unknown |
| `lat`, `lon` | decimal degrees | Empty means unknown |

Empty cells are deliberate. They exercise the unknown-value handling in the profiler and the rule engine.

## logistics_sample.csv

**This file is SYNTHETIC.** The 26 facility rows (depots, shelters, warehouses, hubs) were invented for map and UI testing. The names are generic and the coordinates sit near real Indonesian and Southeast Asian cities, but these are not real facilities, stock levels, or capacities.

**Do not use this data for operational decisions**, disaster response, resource allocation, or public communication.

Columns:

| Column | Type | Notes |
| --- | --- | --- |
| `name` | string | Facility name. Used as the map label. |
| `facility_type` | `DEPOT`, `SHELTER`, `WAREHOUSE` or `HUB` | Its presence marks the dataset as logistics. The Command Center plots it as a logistics layer. |
| `latitude`, `longitude` | decimal degrees | Empty means the site is not plotted. |
| `capacity` | integer | Empty means unknown. Units are not defined. |
| `status` | string | `ACTIVE`, `STANDBY`, `FULL` or `MAINTENANCE`. |

The dataset `kind` field (`CSV` or `GEOJSON`) describes the file format only. A dataset is logistics when its profile includes a `facility_type` column. Any other approved dataset is treated as a disaster dataset.

## Blocked roads (`blocked_roads` tool)

The `blocked_roads` tool writes `blocked_roads.csv` with one row per blocked road. It reads one of these columns, in this order of preference:

| Column | Accepted values | Meaning |
| --- | --- | --- |
| `road_status` | `blocked`, `closed`, `yes`, `true`, `1` count as blocked. Any other non-empty value counts as open. | Text status of the road |
| `road_blocked` | `1` or `true`/`yes` means blocked. `0` or `false`/`no` means open. | Flag per row, as in `flood_incidents_sample.csv` |

Empty cells are unknown. An unknown road status is not listed as blocked. A dataset with neither column cannot be used by `blocked_roads`; the task fails with a clear sandbox error.

`flood_incidents_sample.csv` uses the `road_blocked` column (0 or 1). Its `road_status` column is absent, so the tool reads `road_blocked`.
