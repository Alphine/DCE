"""Response planning from a stored simulation run (SDD 15.1, 14.3 Scenario C "Response Planning").

Read-only and deterministic. The allocation is computed from the run's peak-hour snapshot and the verified
flood pack ratios. It is not saved, not approved and not a mission. To act on it, propose a mission (SDD 15.2).
If the pack has changed since the run, the plan is refused, so an old run is never read with new ratios.
"""

from __future__ import annotations

import json
import math
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.auth import CurrentUser, current_user
from app.container import services_of
from app.errors import AppError
from app.rules import engine
from app.simulation import engine as sim

router = APIRouter(prefix="/planning", tags=["planning"])

# SDD 15.1 lists these. The flood pack has no ratio for them, so they are reported as not estimated.
NOT_ESTIMATED = ["Medical supplies", "Rescue teams", "Transportation", "Fuel", "Communication equipment"]
ALLOCATION_KEYS = ("households_affected", "people_estimated", "water_packs", "food_packs",
                   "shelter_kits", "drinking_water_litres")


def build_allocation(run_row: Any, output: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    ratios = pack["resource_ratios"]
    per_district: dict[str, dict[str, int]] = output["peak"]["per_district"]
    needing = [(name, stats) for name, stats in per_district.items() if stats["affected_rows"] > 0]
    needing.sort(key=lambda item: (-item[1]["affected_rows"], -item[1]["top_severity_rows"], item[0]))

    allocations: list[dict[str, Any]] = []
    for rank, (name, stats) in enumerate(needing, start=1):
        affected = stats["affected_rows"]
        people = affected * ratios["people_per_household"]
        allocations.append({
            "priority_rank": rank,
            "district": name,
            "households_affected": affected,
            "road_blocked_candidates": stats["road_blocked_candidates"],
            "people_estimated": people,
            "water_packs": math.ceil(affected * ratios["water_packs_per_household"]),
            "food_packs": math.ceil(affected * ratios["food_packs_per_household"]),
            "shelter_kits": math.ceil(affected * ratios["shelter_kits_per_household"]),
            "drinking_water_litres": math.ceil(
                people * ratios["drinking_water_litres_per_person_per_day"] * ratios["planning_days"]),
        })

    totals = {key: sum(item[key] for item in allocations) for key in ALLOCATION_KEYS}
    return {
        "data_class": "SIMULATED_FACT",
        "label": sim.LABEL,
        "tool": "response_planner",
        "basis": {
            "simulation": {"id": run_row["id"], "name": run_row["name"]},
            "peak_hour": output["peak"]["hour"],
            "peak_affected_rows": output["peak"]["affected_rows"],
            "output_sha256": run_row["output_sha256"],
            "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack[engine.PACK_HASH_FIELD]},
            "ratios_label": ratios.get("label", "ILLUSTRATIVE"),
        },
        "allocations": allocations,
        "totals": totals,
        "districts_without_need": len(per_district) - len(needing),
        "not_estimated": NOT_ESTIMATED,
        "assumptions": [
            "Allocation uses the peak-hour snapshot of the simulation, not the full timeline.",
            "Each affected row is one household. Ratios are illustrative and not validated against a standard.",
            "Totals add the rounded per-district figures, so they can differ slightly from rounding the total.",
            "Districts with no affected rows at peak receive no allocation.",
        ],
        "not_for_operational_use": True,
    }


@router.get("/allocation")
def allocation(request: Request, simulation_id: str = Query(min_length=36, max_length=36),
               user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    services = services_of(request)
    with services.db.read() as conn:
        row = conn.execute("SELECT * FROM simulation_runs WHERE id = ?", (simulation_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Simulation run not found.")
    _, pack = engine.load_default_pack()
    if pack[engine.PACK_HASH_FIELD] != row["pack_sha256"]:
        raise AppError("CONFLICT",
                       "The rule pack has changed since this simulation ran. Run a new simulation to plan from it.")
    output = json.loads(row["output_json"])
    return build_allocation(row, output, pack)
