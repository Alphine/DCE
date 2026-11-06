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

The backend has no dataset kind field. A dataset is logistics when its profile includes a `facility_type` column. Any other approved dataset is treated as a disaster dataset.
