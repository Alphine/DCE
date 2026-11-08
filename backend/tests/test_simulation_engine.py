"""Pure scenario simulation (SDD 14): timeline arithmetic, peak rule, determinism, budget. No I/O."""

from __future__ import annotations

import pytest

from app.rules import engine
from app.simulation import engine as sim
from tests.conftest import CSV_GOOD


@pytest.fixture
def pack() -> dict:
    return engine.load_default_pack()[1]


@pytest.fixture
def records() -> list[dict]:
    return engine.records_from_csv_bytes(CSV_GOOD)


def test_constant_scaling_applies_the_flood_rules_at_every_hour(records: list[dict], pack: dict) -> None:
    out = sim.run_scenario(records, pack, sim.Params(depth_multiplier=2.0, rise_cm_per_hour=0.0, hours=2))
    assert out["data_class"] == "SIMULATED_FACT"
    assert out["label"] == sim.LABEL
    assert [point["affected_rows"] for point in out["timeline"]] == [3, 3, 3]
    assert out["timeline"][0]["counts_by_severity"]["UNKNOWN"] == 1
    assert out["timeline"][0]["road_blocked_candidates"] == 3
    assert out["peak"]["hour"] == 0


def test_rise_moves_depth_linearly_and_peak_keeps_the_first_maximum(records: list[dict], pack: dict) -> None:
    out = sim.run_scenario(records, pack, sim.Params(depth_multiplier=1.0, rise_cm_per_hour=20.0, hours=3))
    assert [point["affected_rows"] for point in out["timeline"]] == [0, 3, 5, 5]
    assert out["peak"]["hour"] == 2
    assert out["peak"]["affected_rows"] == 5


def test_peak_per_district_matches_the_peak_hour(records: list[dict], pack: dict) -> None:
    out = sim.run_scenario(records, pack, sim.Params(depth_multiplier=1.0, rise_cm_per_hour=20.0, hours=3))
    per = out["peak"]["per_district"]
    assert per["Kemang"]["affected_rows"] == 2
    assert sum(stats["affected_rows"] for stats in per.values()) == out["peak"]["affected_rows"]


def test_unknown_base_depth_stays_unknown_at_every_hour(records: list[dict], pack: dict) -> None:
    out = sim.run_scenario(records, pack, sim.Params(depth_multiplier=3.0, rise_cm_per_hour=100.0, hours=4))
    assert out["rows_unknown_base_depth"] == 1
    assert all(point["counts_by_severity"]["UNKNOWN"] == 1 for point in out["timeline"])


def test_same_inputs_give_identical_output(records: list[dict], pack: dict) -> None:
    params = sim.Params(depth_multiplier=1.5, rise_cm_per_hour=12.5, hours=10)
    first = engine.canonical_json(sim.run_scenario(records, pack, params))
    second = engine.canonical_json(sim.run_scenario(records, pack, params))
    assert first == second


def test_the_budget_refuses_large_scenarios() -> None:
    sim.check_budget(1_000_000, 0)
    with pytest.raises(sim.ScenarioTooLarge):
        sim.check_budget(1_000_000, 1)
    with pytest.raises(sim.ScenarioTooLarge):
        sim.check_budget(20_000, sim.MAX_HOURS)


def test_classify_depth_agrees_with_evaluate_hazards(records: list[dict], pack: dict) -> None:
    # The refactor must keep Hazard Intelligence unchanged: per-row severity equals classify_depth's answer.
    result = engine.evaluate_hazards(records, pack)
    for item in result["results"]:
        severity, flags = engine.classify_depth(item["water_depth_cm"], pack)
        assert item["severity"] == severity
        assert item["flags"] == sorted(flags)
