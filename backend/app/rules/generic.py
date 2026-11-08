"""Shared, hash-checked rule-pack loader and deterministic evaluator for the earthquake and wildfire packs.

Same contract as app/rules/engine.py and app/rules/tsunami.py: pure functions, the same records and the same
verified pack give the same output, and the model never supplies or changes rules. Thresholds are illustrative
and not validated (SDD 11.3). A rule fires only when every condition is known to be true. A row whose severity
cannot be decided and no rule fired is UNKNOWN, never LOW. Unknown is not zero.

A pack may declare an optional "countries" list of ISO 3166-1 alpha-2 codes. A missing field means [] (any country).
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from typing import Any

from app.rules.engine import (
    ILLUSTRATIVE_STATUS,
    PACK_HASH_FIELD,
    RulePackError,
    pack_body_sha256,
)

NAME_CANDIDATES = ("district", "district_name", "location")
TRUE_TEXT = frozenset({"true", "1", "yes", "y"})
FALSE_TEXT = frozenset({"false", "0", "no", "n"})
COMPARATORS = (("_gte", "gte"), ("_lte", "lte"), ("_lt", "lt"))


@dataclass(frozen=True)
class PackSpec:
    """What one hazard's packs may contain. Anything outside this spec is refused at load time."""

    hazard: str
    tool: str
    required: tuple[str, ...]
    numeric: tuple[str, ...]
    boolean: tuple[str, ...]
    flags: frozenset[str]


def _reject_constant(name: str) -> Any:
    raise RulePackError(f"non-finite constant in rule pack: {name}")


def parse_generic_pack(data: bytes, spec: PackSpec) -> dict[str, Any]:
    """Parse and verify a pack for `spec`. Raises RulePackError on a hash mismatch or a malformed pack."""
    try:
        pack = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RulePackError(f"{spec.hazard} rule pack is not valid JSON") from exc
    if not isinstance(pack, dict):
        raise RulePackError(f"{spec.hazard} rule pack must be a JSON object")
    recorded = pack.get(PACK_HASH_FIELD)
    if not isinstance(recorded, str) or recorded != pack_body_sha256(pack):
        raise RulePackError(f"{spec.hazard} rule pack hash mismatch: refusing to load")
    _validate_generic_shape(pack, spec)
    return pack


def _validate_generic_shape(pack: dict[str, Any], spec: PackSpec) -> None:
    for key in ("pack_id", "version", "thresholds_label", "hazard", "status_note"):
        if not isinstance(pack.get(key), str) or not pack[key]:
            raise RulePackError(f"{spec.hazard} rule pack field missing: {key}")
    if pack["hazard"] != spec.hazard:
        raise RulePackError(f"this engine only loads {spec.hazard} packs")
    if pack["thresholds_label"] != "illustrative":
        raise RulePackError("this engine requires thresholds labelled illustrative")
    _validate_countries(pack.get("countries", []))
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
            raise RulePackError("rule is malformed")
        for key in when:
            _parse_condition(key, when[key], spec)
        if "flag" in then and then["flag"] not in spec.flags:
            raise RulePackError("rule flag is not recognised")
        if "severity" in then and then["severity"] not in order:
            raise RulePackError("rule severity is not in severity_order")
        if set(then) - {"flag", "severity"} or not then:
            raise RulePackError("rule action is not recognised")


def _validate_countries(countries: Any) -> None:
    if not isinstance(countries, list):
        raise RulePackError("countries must be a list")
    for code in countries:
        if not isinstance(code, str) or len(code) != 2 or not code.isalpha() or not code.isupper():
            raise RulePackError("countries must be ISO 3166-1 alpha-2 codes")


def _parse_condition(key: str, value: Any, spec: PackSpec) -> tuple[str, str, Any]:
    """Return (column, operator, threshold). Operator 'true' is for boolean columns, which must be true."""
    if key in spec.boolean:
        if value is not True:
            raise RulePackError(f"{key} condition must be true")
        return key, "true", None
    for suffix, op in COMPARATORS:
        if key.endswith(suffix) and key[: -len(suffix)] in spec.numeric:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RulePackError("rule threshold must be a finite number")
            return key[: -len(suffix)], op, float(value)
    raise RulePackError("rule condition is not recognised")


def _find_column(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered: dict[str, str] = {}
    for field in fields:
        lowered.setdefault(field.strip().lower(), field)
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _to_number(text: str | None) -> float | None:
    # Empty, non-numeric, NaN and infinite values are unknown, never zero.
    if text is None or text.strip() == "":
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _to_bool(text: str | None) -> bool | None:
    if text is None:
        return None
    lowered = text.strip().lower()
    if lowered in TRUE_TEXT:
        return True
    if lowered in FALSE_TEXT:
        return False
    return None


def records_from_csv(data: bytes, spec: PackSpec) -> list[dict[str, Any]]:
    """Normalised records. Raises ValueError when a column the pack needs is absent (the route maps it to 422)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    columns: dict[str, str | None] = {}
    for name in spec.required + spec.numeric + spec.boolean:
        columns[name] = _find_column(fields, (name,))
    for name in spec.required:
        if columns[name] is None:
            raise ValueError(f"missing required column: {name}")
    name_col = _find_column(fields, NAME_CANDIDATES)
    records: list[dict[str, Any]] = []
    for number, row in enumerate(reader, start=1):
        item: dict[str, Any] = {
            "row": number,
            "district": ((row.get(name_col) or "").strip() if name_col else "") or "unknown",
        }
        for name in spec.numeric:
            item[name] = _to_number(row.get(columns[name])) if columns[name] else None
        for name in spec.boolean:
            item[name] = _to_bool(row.get(columns[name])) if columns[name] else None
        records.append(item)
    return records


def _evaluate_condition(column: str, op: str, threshold: Any, record: dict[str, Any]) -> bool | None:
    value = record[column]
    if value is None:
        return None
    if op == "true":
        return value is True
    if op == "gte":
        return value >= threshold
    if op == "lte":
        return value <= threshold
    return value < threshold


def evaluate_generic(records: list[dict[str, Any]], pack: dict[str, Any], spec: PackSpec) -> dict[str, Any]:
    """Apply the verified pack's rules to each record. Pure and deterministic."""
    order: list[str] = pack["severity_order"]
    rank = {level: index for index, level in enumerate(order)}
    parsed = [
        (rule, [_parse_condition(key, value, spec) for key, value in rule["when"].items()])
        for rule in pack["rules"]
    ]
    counts: dict[str, int] = {level: 0 for level in order}
    counts["UNKNOWN"] = 0
    flag_counts: dict[str, int] = {flag: 0 for flag in sorted(spec.flags)}
    results: list[dict[str, Any]] = []

    for record in sorted(records, key=lambda item: item["row"]):
        fired_severity: str | None = None
        flags: set[str] = set()
        undecided = False
        for rule, conditions in parsed:
            outcomes = [_evaluate_condition(col, op, thr, record) for col, op, thr in conditions]
            if any(outcome is False for outcome in outcomes):
                continue
            if any(outcome is None for outcome in outcomes):
                # Only an undecided severity rule makes the row UNKNOWN. An undecided flag never changes severity.
                undecided = undecided or "severity" in rule["then"]
                continue
            action = rule["then"]
            if "flag" in action:
                flags.add(action["flag"])
            if "severity" in action and (fired_severity is None or rank[action["severity"]] > rank[fired_severity]):
                fired_severity = action["severity"]
        if fired_severity is not None:
            severity = fired_severity
        elif undecided:
            severity = "UNKNOWN"
        else:
            severity = order[0]
        counts[severity] += 1
        for flag in flags:
            flag_counts[flag] += 1
        item = {"row": record["row"], "district": record["district"]}
        item.update({name: record[name] for name in spec.required + spec.numeric + spec.boolean})
        item["severity"] = severity
        item["flags"] = sorted(flags)
        results.append(item)

    return {
        "data_class": "INFERRED_FACT",
        "tool": spec.tool,
        "rule_pack": {
            "pack_id": pack["pack_id"],
            "version": pack["version"],
            "sha256": pack[PACK_HASH_FIELD],
            "countries": list(pack.get("countries", [])),
        },
        "thresholds": {"label": pack["thresholds_label"], "status": ILLUSTRATIVE_STATUS, "rules": pack["rules"],
                       "pack_status": pack["status_note"]},
        "rows_evaluated": len(results),
        "counts_by_severity": dict(sorted(counts.items())),
        "flag_counts": flag_counts,
        "results": results,
        "not_for_operational_use": True,
    }
