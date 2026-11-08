"""Response planning from a stored run (SDD 15.1): arithmetic, ranking, roles, pack-change refusal."""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.rules import engine
from tests.conftest import Env

ZERO_ID = "00000000-0000-4000-8000-000000000000"


def _run(env: Env, **overrides: Any) -> str:
    body: dict[str, Any] = {"dataset_id": env.approved_dataset(), "name": "Plan base",
                            "depth_multiplier": 2.0, "rise_cm_per_hour": 0.0, "hours": 2}
    body.update(overrides)
    response = env.api("POST", "/api/simulations", env.token("analyst"), json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _allocation(env: Env, run_id: str, username: str = "viewer") -> Any:
    return env.api("GET", f"/api/planning/allocation?simulation_id={run_id}", env.token(username))


def test_allocation_matches_the_hand_calculation(env: Env) -> None:
    # Peak snapshot (multiplier 2, hour 0): Kemang 2 affected, Tebet 1 affected, others 0.
    response = _allocation(env, _run(env))
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["data_class"] == "SIMULATED_FACT"
    assert [row["district"] for row in plan["allocations"]] == ["Kemang", "Tebet"]
    kemang, tebet = plan["allocations"]
    assert kemang["priority_rank"] == 1 and tebet["priority_rank"] == 2
    # Pack ratios: 4 people per household, 1 water pack, 1 food pack, 0.5 shelter kit, 3 L/day, 3 days.
    assert kemang["households_affected"] == 2
    assert kemang["people_estimated"] == 8
    assert kemang["water_packs"] == 2 and kemang["food_packs"] == 2
    assert kemang["shelter_kits"] == math.ceil(2 * 0.5)
    assert kemang["drinking_water_litres"] == 8 * 3 * 3
    assert tebet["shelter_kits"] == math.ceil(1 * 0.5)
    assert plan["totals"] == {"households_affected": 3, "people_estimated": 12, "water_packs": 3,
                              "food_packs": 3, "shelter_kits": 2, "drinking_water_litres": 108}
    assert plan["districts_without_need"] == 2


def test_plan_lists_what_is_not_estimated(env: Env) -> None:
    plan = _allocation(env, _run(env)).json()
    assert "Rescue teams" in plan["not_estimated"]
    assert plan["not_for_operational_use"] is True


def test_plan_basis_points_to_the_run_and_its_pack(env: Env) -> None:
    run_id = _run(env)
    plan = _allocation(env, run_id).json()
    assert plan["basis"]["simulation"]["id"] == run_id
    assert plan["basis"]["peak_hour"] == 0
    assert plan["basis"]["rule_pack"]["sha256"]


def test_analyst_and_viewer_may_read_a_plan(env: Env) -> None:
    run_id = _run(env)
    assert _allocation(env, run_id, username="analyst").status_code == 200
    assert _allocation(env, run_id, username="viewer").status_code == 200


def test_unknown_run_is_not_found(env: Env) -> None:
    response = _allocation(env, ZERO_ID)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_plan_is_refused_when_the_pack_changed_since_the_run(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = _run(env)
    real_load = engine.load_default_pack

    def changed_pack() -> tuple[bytes, dict[str, Any]]:
        data, pack = real_load()
        return data, {**pack, engine.PACK_HASH_FIELD: "0" * 64}

    monkeypatch.setattr(engine, "load_default_pack", changed_pack)
    response = _allocation(env, run_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_no_allocation_when_nothing_is_affected(env: Env) -> None:
    run_id = _run(env, depth_multiplier=0.1, hours=1)
    plan = _allocation(env, run_id).json()
    assert plan["allocations"] == []
    assert plan["totals"]["households_affected"] == 0
    assert plan["districts_without_need"] == 4
