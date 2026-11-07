"""Earthquake-to-tsunami rule engine (SDD D3, illustrative). Pure-engine tests, no network, no sandbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rules.engine import RulePackError, pack_body_sha256
from app.rules.tsunami import (
    evaluate_tsunami,
    load_default_tsunami_pack,
    parse_tsunami_pack,
    records_from_csv_bytes,
)

SAMPLE = Path(__file__).resolve().parents[2] / "datasets" / "samples" / "earthquake_sample.csv"


def _pack() -> dict:
    _, pack = load_default_tsunami_pack()
    return pack


def _record(**overrides) -> dict:
    base = {"row": 1, "area": "x", "magnitude": 6.0, "depth_km": 20.0, "coast_distance_km": 50.0}
    base.update(overrides)
    return base


def test_default_pack_loads_and_hash_matches() -> None:
    data, pack = load_default_tsunami_pack()
    assert pack["hazard"] == "earthquake_tsunami"
    assert pack["thresholds_label"] == "illustrative"
    assert pack["pack_sha256"] == pack_body_sha256(pack)
    assert parse_tsunami_pack(data) == pack


def test_tampered_pack_is_refused() -> None:
    data, _ = load_default_tsunami_pack()
    tampered = json.loads(data)
    tampered["rules"][0]["when"]["magnitude_gte"] = 9.0
    with pytest.raises(RulePackError, match="hash mismatch"):
        parse_tsunami_pack(json.dumps(tampered).encode("utf-8"))


def test_flood_pack_is_not_accepted_as_tsunami() -> None:
    flood = Path(__file__).resolve().parents[1] / "app" / "rules" / "flood_v1.json"
    with pytest.raises(RulePackError):
        parse_tsunami_pack(flood.read_bytes())


def test_shallow_strong_coastal_quake_is_high_and_flagged() -> None:
    result = evaluate_tsunami([_record(magnitude=7.2, depth_km=30, coast_distance_km=45)], _pack())
    row = result["results"][0]
    assert row["severity"] == "HIGH"
    assert row["flags"] == ["tsunami_watch_candidate"]
    assert result["watch_candidates"] == 1


def test_deep_quake_does_not_fire_shallow_rules() -> None:
    result = evaluate_tsunami([_record(magnitude=7.5, depth_km=95, coast_distance_km=20)], _pack())
    assert result["results"][0]["severity"] == "LOW"
    assert result["results"][0]["flags"] == []


def test_medium_band() -> None:
    result = evaluate_tsunami([_record(magnitude=6.6, depth_km=40, coast_distance_km=22)], _pack())
    assert result["results"][0]["severity"] == "MEDIUM"


def test_inland_quake_is_not_coastal_rule() -> None:
    result = evaluate_tsunami([_record(magnitude=6.9, depth_km=95, coast_distance_km=180)], _pack())
    assert result["results"][0]["flags"] == []


def test_unknown_magnitude_is_unknown_never_zero() -> None:
    result = evaluate_tsunami([_record(magnitude=None)], _pack())
    assert result["results"][0]["severity"] == "UNKNOWN"
    assert result["counts_by_severity"]["UNKNOWN"] == 1


def test_missing_depth_with_strong_magnitude_is_unknown() -> None:
    result = evaluate_tsunami([_record(magnitude=7.0, depth_km=None, coast_distance_km=50)], _pack())
    assert result["results"][0]["severity"] == "UNKNOWN"


def test_highest_fired_severity_wins() -> None:
    # Matches R1 (HIGH) and R2 (MEDIUM) at once: HIGH must win.
    result = evaluate_tsunami([_record(magnitude=7.2, depth_km=30, coast_distance_km=45)], _pack())
    assert result["results"][0]["severity"] == "HIGH"


def test_sample_dataset_is_deterministic_and_marked_illustrative() -> None:
    records = records_from_csv_bytes(SAMPLE.read_bytes())
    first = evaluate_tsunami(records, _pack())
    second = evaluate_tsunami(records, _pack())
    assert first == second
    assert first["rows_evaluated"] == 15
    assert first["counts_by_severity"]["UNKNOWN"] == 2
    assert first["data_class"] == "INFERRED_FACT"
    assert first["not_for_operational_use"] is True
    assert "ILLUSTRATIVE" in first["thresholds"]["status"]
