"""Earthquake-to-tsunami rule engine (SDD decision D3, illustrative).

Pure functions, same contract as app/rules/engine.py: the same records and the same verified pack give the
same output, and the model never supplies or changes rules. Thresholds are illustrative and not validated.

A rule fires only when every condition is known to be true. If no rule fires and a needed input is
unknown, the row is UNKNOWN, never LOW. Unknown is not zero.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

from app.rules.engine import (
    ILLUSTRATIVE_STATUS,
    PACK_HASH_FIELD,
    RulePackError,
    pack_body_sha256,
)

DEFAULT_TSUNAMI_PACK_PATH = Path(__file__).with_name("tsunami_v1.json")
HAZARD_NAME = "earthquake_tsunami"
NAME_CANDIDATES = ("area", "area_name", "district", "location")
MAGNITUDE_COLUMN = "magnitude"
DEPTH_COLUMN = "depth_km"
COAST_COLUMN = "coast_distance_km"
CONDITION_FIELDS = {
    "magnitude_gte": "magnitude",
    "depth_km_lt": "depth_km",
    "coast_distance_km_lte": "coast_distance_km",
}
ALLOWED_FLAGS = frozenset({"tsunami_watch_candidate"})


def _reject_constant(name: str) -> Any:
    raise RulePackError(f"non-finite constant in rule pack: {name}")


def parse_tsunami_pack(data: bytes) -> dict[str, Any]:
    """Parse and verify a tsunami pack. Raises RulePackError on a hash mismatch or a malformed pack."""
    try:
        pack = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RulePackError("tsunami rule pack is not valid JSON") from exc
    if not isinstance(pack, dict):
        raise RulePackError("tsunami rule pack must be a JSON object")
    recorded = pack.get(PACK_HASH_FIELD)
    if not isinstance(recorded, str) or recorded != pack_body_sha256(pack):
        raise RulePackError("tsunami rule pack hash mismatch: refusing to load")
    _validate_tsunami_shape(pack)
    return pack


def _validate_tsunami_shape(pack: dict[str, Any]) -> None:
    for key in ("pack_id", "version", "thresholds_label", "hazard"):
        if not isinstance(pack.get(key), str) or not pack[key]:
            raise RulePackError(f"tsunami rule pack field missing: {key}")
    if pack["hazard"] != HAZARD_NAME:
        raise RulePackError("this engine only loads earthquake_tsunami packs")
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
        if not isinstance(when, dict) or not when or not isinstance(then, dict) or not isinstance(rule.get("id"), str):
            raise RulePackError("tsunami rule is malformed")
        if set(when) - set(CONDITION_FIELDS):
            raise RulePackError("tsunami rule condition is not recognised")
        for key, value in when.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RulePackError("tsunami rule threshold must be a finite number")
        if "flag" in then and then["flag"] not in ALLOWED_FLAGS:
            raise RulePackError("tsunami rule flag is not recognised")
        if "severity" in then and then["severity"] not in order:
            raise RulePackError("tsunami rule severity is not in severity_order")
        if set(then) - {"flag", "severity"}:
            raise RulePackError("tsunami rule action is not recognised")


def load_default_tsunami_pack() -> tuple[bytes, dict[str, Any]]:
    data = DEFAULT_TSUNAMI_PACK_PATH.read_bytes()
    return data, parse_tsunami_pack(data)


def _to_number(text: str | None) -> float | None:
    # Empty, non-numeric, NaN and infinite values are unknown, never zero.
    if text is None or text.strip() == "":
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _find_name_column(fields: list[str]) -> str | None:
    lowered: dict[str, str] = {}
    for field in fields:
        lowered.setdefault(field.strip().lower(), field)
    for candidate in NAME_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    return None


def records_from_csv_bytes(data: bytes) -> list[dict[str, Any]]:
    """Normalised records: {row, area, magnitude, depth_km, coast_distance_km} (None means unknown)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    name_col = _find_name_column(fields)
    records: list[dict[str, Any]] = []
    for number, row in enumerate(reader, start=1):
        area = (row.get(name_col) or "").strip() if name_col else ""
        records.append({
            "row": number,
            "area": area or "unknown",
            "magnitude": _to_number(row.get(MAGNITUDE_COLUMN)),
            "depth_km": _to_number(row.get(DEPTH_COLUMN)),
            "coast_distance_km": _to_number(row.get(COAST_COLUMN)),
        })
    return records


def _condition(key: str, threshold: float, record: dict[str, Any]) -> bool | None:
    value = record[CONDITION_FIELDS[key]]
    if value is None:
        return None
    if key == "magnitude_gte":
        return value >= threshold
    if key == "depth_km_lt":
        return value < threshold
    return value <= threshold


def evaluate_tsunami(records: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    """Apply the verified pack's rules to each record. Pure and deterministic."""
    order: list[str] = pack["severity_order"]
    rank = {level: index for index, level in enumerate(order)}
    counts: dict[str, int] = {level: 0 for level in order}
    counts["UNKNOWN"] = 0
    results: list[dict[str, Any]] = []

    for record in sorted(records, key=lambda item: item["row"]):
        fired_severity: str | None = None
        flags: set[str] = set()
        undecided = False
        for rule in pack["rules"]:
            outcomes = [_condition(key, threshold, record) for key, threshold in rule["when"].items()]
            if all(outcome is True for outcome in outcomes):
                action = rule["then"]
                if "flag" in action:
                    flags.add(action["flag"])
                if "severity" in action and (fired_severity is None or rank[action["severity"]] > rank[fired_severity]):
                    fired_severity = action["severity"]
            elif any(outcome is None for outcome in outcomes):
                undecided = True
        if fired_severity is not None:
            severity = fired_severity
        elif undecided:
            severity = "UNKNOWN"
        else:
            severity = order[0]
        counts[severity] += 1
        results.append({
            "row": record["row"],
            "area": record["area"],
            "magnitude": record["magnitude"],
            "depth_km": record["depth_km"],
            "coast_distance_km": record["coast_distance_km"],
            "severity": severity,
            "flags": sorted(flags),
        })

    return {
        "data_class": "INFERRED_FACT",
        "tool": "tsunami_analyzer",
        "rule_pack": {"pack_id": pack["pack_id"], "version": pack["version"], "sha256": pack[PACK_HASH_FIELD]},
        "thresholds": {"label": pack["thresholds_label"], "status": ILLUSTRATIVE_STATUS, "rules": pack["rules"]},
        "rows_evaluated": len(results),
        "counts_by_severity": dict(sorted(counts.items())),
        "watch_candidates": sum(1 for item in results if "tsunami_watch_candidate" in item["flags"]),
        "results": results,
        "not_for_operational_use": True,
    }
