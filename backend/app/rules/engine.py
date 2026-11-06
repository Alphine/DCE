"""Deterministic rule engine (SDD 11.2 to 11.4).

Pure functions: the same records and the same verified rule pack give the same output. The model never
supplies or changes rules. The sandbox script (app/agent/mock_script.py) implements the same arithmetic in
standard library form; tests check that both produce identical output for the same CSV.

Pack integrity: the pack's `pack_sha256` field must equal the SHA-256 of its canonical body (every field
except `pack_sha256`, serialised with sorted keys and compact separators). A mismatch is refused.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_PACK_PATH = Path(__file__).with_name("flood_v1.json")
PACK_HASH_FIELD = "pack_sha256"
DISTRICT_CANDIDATES = ("district", "district_name", "location")
DEPTH_COLUMN = "water_depth_cm"
ILLUSTRATIVE_STATUS = "ILLUSTRATIVE: not validated against an authoritative standard (SDD 11.3)"


class RulePackError(Exception):
    """Raised when a rule pack cannot be loaded. `code` is the machine-readable error reason."""

    code = "RULE_PACK_INTEGRITY"


def pack_body_bytes(pack: dict[str, Any]) -> bytes:
    body = {key: value for key, value in pack.items() if key != PACK_HASH_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def pack_body_sha256(pack: dict[str, Any]) -> str:
    return hashlib.sha256(pack_body_bytes(pack)).hexdigest()


def _reject_constant(name: str) -> Any:
    raise RulePackError(f"non-finite constant in rule pack: {name}")


def parse_pack(data: bytes) -> dict[str, Any]:
    """Parse and verify a rule pack. Raises RulePackError on a hash mismatch or a malformed pack."""
    try:
        pack = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RulePackError("rule pack is not valid JSON") from exc
    if not isinstance(pack, dict):
        raise RulePackError("rule pack must be a JSON object")
    recorded = pack.get(PACK_HASH_FIELD)
    if not isinstance(recorded, str) or recorded != pack_body_sha256(pack):
        raise RulePackError("rule pack hash mismatch: refusing to load")
    _validate_shape(pack)
    return pack


def _validate_shape(pack: dict[str, Any]) -> None:
    for key in ("pack_id", "version", "thresholds_label"):
        if not isinstance(pack.get(key), str) or not pack[key]:
            raise RulePackError(f"rule pack field missing: {key}")
    if pack["thresholds_label"] != "illustrative":
        raise RulePackError("this engine requires thresholds labelled illustrative")
    order = pack.get("severity_order")
    if not isinstance(order, list) or not order or not all(isinstance(level, str) for level in order):
        raise RulePackError("severity_order is malformed")
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RulePackError("rules is malformed")
    for rule in rules:
        when = rule.get("when") if isinstance(rule, dict) else None
        then = rule.get("then") if isinstance(rule, dict) else None
        if not isinstance(when, dict) or not isinstance(then, dict) or not isinstance(rule.get("id"), str):
            raise RulePackError("rule is malformed")
        threshold = when.get("water_depth_cm_gte")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise RulePackError("rule threshold must be a finite number")
        if "flag" in then and then["flag"] != "road_blocked_candidate":
            raise RulePackError("rule flag is not recognised")
        if "severity" in then and then["severity"] not in order:
            raise RulePackError("rule severity is not in severity_order")
        if set(then) - {"flag", "severity"}:
            raise RulePackError("rule action is not recognised")
    ratios = pack.get("resource_ratios")
    if not isinstance(ratios, dict):
        raise RulePackError("resource_ratios is missing")


def load_default_pack() -> tuple[bytes, dict[str, Any]]:
    """Read the default pack and verify it. Returns (raw bytes to stage in the sandbox, verified pack)."""
    data = DEFAULT_PACK_PATH.read_bytes()
    return data, parse_pack(data)


def _to_number(text: str | None) -> float | None:
    # None means unknown. Empty, non-numeric, NaN and infinite values are unknown, never zero.
    if text is None or text.strip() == "":
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _find_column(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered: dict[str, str] = {}
    for field in fields:
        lowered.setdefault(field.strip().lower(), field)
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def records_from_csv_bytes(data: bytes) -> list[dict[str, Any]]:
    """Normalised records: {row (1-based data row), district, water_depth_cm (float or None)}."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    district_col = _find_column(fields, DISTRICT_CANDIDATES)
    depth_col = _find_column(fields, (DEPTH_COLUMN,))
    records: list[dict[str, Any]] = []
    for number, row in enumerate(reader, start=1):
        name = (row.get(district_col) or "").strip() if district_col else ""
        records.append({
            "row": number,
            "district": name or "unknown",
            "water_depth_cm": _to_number(row.get(depth_col)) if depth_col else None,
        })
    return records


def evaluate_hazards(records: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    """Apply the verified pack's rules to each record. Pure and deterministic."""
    order: list[str] = pack["severity_order"]
    rank = {level: index for index, level in enumerate(order)}
    counts: dict[str, int] = {level: 0 for level in order}
    counts["UNKNOWN"] = 0
    per_district: dict[str, dict[str, int]] = {}
    results: list[dict[str, Any]] = []

    for record in sorted(records, key=lambda item: item["row"]):
        depth = record["water_depth_cm"]
        flags: set[str] = set()
        if depth is None:
            severity = "UNKNOWN"
        else:
            severity = order[0]
            for rule in pack["rules"]:
                if depth >= rule["when"]["water_depth_cm_gte"]:
                    action = rule["then"]
                    if "flag" in action:
                        flags.add(action["flag"])
                    if "severity" in action and rank[action["severity"]] > rank[severity]:
                        severity = action["severity"]
        counts[severity] += 1
        district = per_district.setdefault(record["district"], {
            "rows": 0, "road_blocked_candidates": 0, "unknown_depth_rows": 0,
        })
        district["rows"] += 1
        district["road_blocked_candidates"] += 1 if "road_blocked_candidate" in flags else 0
        district["unknown_depth_rows"] += 1 if depth is None else 0
        results.append({
            "row": record["row"],
            "district": record["district"],
            "water_depth_cm": depth,
            "severity": severity,
            "flags": sorted(flags),
        })

    return {
        "data_class": "INFERRED_FACT",
        "tool": "hazard_analyzer",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack[PACK_HASH_FIELD]},
        "thresholds": {"label": pack["thresholds_label"], "status": ILLUSTRATIVE_STATUS, "rules": pack["rules"]},
        "rows_evaluated": len(results),
        "rows_unknown_depth": counts["UNKNOWN"],
        "counts_by_severity": dict(sorted(counts.items())),
        "road_blocked_candidates": sum(1 for item in results if "road_blocked_candidate" in item["flags"]),
        "per_district": dict(sorted(per_district.items())),
        "results": results,
    }


def estimate_resources(records: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    """Illustrative resource estimate from affected row counts and the pack's ratios. SIMULATED_FACT."""
    ratios = pack["resource_ratios"]
    threshold = ratios["affected_depth_cm_gte"]
    affected = sum(1 for item in records if item["water_depth_cm"] is not None and item["water_depth_cm"] >= threshold)
    unknown = sum(1 for item in records if item["water_depth_cm"] is None)
    people = affected * ratios["people_per_household"]
    litres = people * ratios["drinking_water_litres_per_person_per_day"] * ratios["planning_days"]
    return {
        "data_class": "SIMULATED_FACT",
        "tool": "resource_estimator",
        "label": "ILLUSTRATIVE ratios",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack[PACK_HASH_FIELD]},
        "inputs": {
            "rows_total": len(records),
            "affected_rows": affected,
            "unknown_depth_rows": unknown,
            "affected_depth_cm_gte": threshold,
        },
        "ratios": {key: value for key, value in ratios.items() if key != "label"},
        "estimates": {
            "households_affected": affected,
            "people_estimated": people,
            "water_packs": math.ceil(affected * ratios["water_packs_per_household"]),
            "food_packs": math.ceil(affected * ratios["food_packs_per_household"]),
            "shelter_kits": math.ceil(affected * ratios["shelter_kits_per_household"]),
            "drinking_water_litres_total": math.ceil(litres),
        },
        "assumptions": [
            "Each affected row is treated as one household (illustrative).",
            "Ratios are illustrative and not validated against an authoritative standard.",
            "Rows with unknown water depth are not counted as affected.",
        ],
        "not_for_operational_use": True,
    }


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode("ascii")
