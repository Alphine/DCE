"""Deterministic what-if scenario simulation (SDD 14.2 to 14.5).

The model is deliberately simple and fully stated. For each hour t from 0 to `hours`, every row's depth is

    depth(t) = base_depth * depth_multiplier + rise_cm_per_hour * t

Severity and road-blocked flags come from the verified flood rule pack (engine.classify_depth), so a
simulation applies the same rules as Hazard Intelligence. Rows with an unknown base depth stay unknown at
every hour. No randomness is used, so the same dataset, parameters and pack give the same output bytes.

Output is SIMULATED_FACT and is labelled "illustrative parameters" (SDD 14.5). It is not an observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rules import engine

SIMULATOR_VERSION = "sim-1.0.0"
LABEL = "Simulation — illustrative parameters"
MAX_HOURS = 72
MAX_DEPTH_MULTIPLIER = 3.0
MIN_DEPTH_MULTIPLIER = 0.1
MAX_RISE_CM_PER_HOUR = 100.0
# Rows times time steps. Keeps one run inside the SDD 23 target of a few seconds on CPU.
MAX_ROW_STEPS = 1_000_000


class ScenarioTooLarge(ValueError):
    """The dataset and horizon together exceed the simulation budget."""


@dataclass(frozen=True)
class Params:
    depth_multiplier: float
    rise_cm_per_hour: float
    hours: int

    def as_dict(self) -> dict[str, Any]:
        return {"depth_multiplier": self.depth_multiplier, "rise_cm_per_hour": self.rise_cm_per_hour,
                "hours": self.hours}


def check_budget(rows: int, hours: int) -> None:
    steps = rows * (hours + 1)
    if steps > MAX_ROW_STEPS:
        raise ScenarioTooLarge(
            f"This scenario is too large: {rows} rows over {hours} hours. "
            f"Reduce the horizon or use a smaller dataset (limit {MAX_ROW_STEPS:,} row-hours).")


def _depth_at(base: float | None, params: Params, hour: int) -> float | None:
    if base is None:
        return None
    return round(base * params.depth_multiplier + params.rise_cm_per_hour * hour, 2)


def run_scenario(records: list[dict[str, Any]], pack: dict[str, Any], params: Params) -> dict[str, Any]:
    """Run the scenario over every hour. Pure: no I/O, no clock, no randomness."""
    order: list[str] = pack["severity_order"]
    top_level = order[-1]
    threshold = pack["resource_ratios"]["affected_depth_cm_gte"]
    rows = sorted(records, key=lambda item: item["row"])

    timeline: list[dict[str, Any]] = []
    peak: dict[str, Any] = {"hour": 0, "affected_rows": -1, "per_district": {}}

    for hour in range(params.hours + 1):
        counts: dict[str, int] = {level: 0 for level in order}
        counts["UNKNOWN"] = 0
        affected = 0
        road_blocked = 0
        per_district: dict[str, dict[str, int]] = {}

        for record in rows:
            depth = _depth_at(record["water_depth_cm"], params, hour)
            severity, flags = engine.classify_depth(depth, pack)
            counts[severity] += 1
            is_affected = depth is not None and depth >= threshold
            is_blocked = "road_blocked_candidate" in flags
            affected += 1 if is_affected else 0
            road_blocked += 1 if is_blocked else 0
            district = per_district.setdefault(record["district"], {
                "rows": 0, "affected_rows": 0, "road_blocked_candidates": 0, "top_severity_rows": 0,
            })
            district["rows"] += 1
            district["affected_rows"] += 1 if is_affected else 0
            district["road_blocked_candidates"] += 1 if is_blocked else 0
            district["top_severity_rows"] += 1 if severity == top_level else 0

        timeline.append({
            "hour": hour,
            "counts_by_severity": dict(sorted(counts.items())),
            "affected_rows": affected,
            "road_blocked_candidates": road_blocked,
        })
        # Strictly greater keeps the first hour that reaches the peak, so ties resolve deterministically.
        if affected > peak["affected_rows"]:
            peak = {"hour": hour, "affected_rows": affected,
                    "per_district": dict(sorted(per_district.items()))}

    unknown_base = sum(1 for record in rows if record["water_depth_cm"] is None)
    return {
        "data_class": "SIMULATED_FACT",
        "label": LABEL,
        "tool": "scenario_simulator",
        "simulator_version": SIMULATOR_VERSION,
        "model": "depth(t) = base_depth * depth_multiplier + rise_cm_per_hour * t, for t = 0..hours",
        "parameters": params.as_dict(),
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack[engine.PACK_HASH_FIELD]},
        "affected_depth_cm_gte": threshold,
        "rows_total": len(rows),
        "rows_unknown_base_depth": unknown_base,
        "timeline": timeline,
        "peak": peak,
        "assumptions": [
            "Depth rises linearly with time at the stated rate. Real flood dynamics are not modelled.",
            "Each row is one location. Rows with an unknown base depth stay unknown at every hour.",
            "Severity and road-blocked flags use the illustrative flood rule pack.",
            "No randomness is used. The same inputs give the same output.",
        ],
        "not_for_operational_use": True,
    }
