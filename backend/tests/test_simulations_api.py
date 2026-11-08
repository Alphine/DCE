"""Simulation runs over approved CSVs (SDD 14): roles, validation, reproducibility, audit, persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rules import engine
from app.util import sha256_bytes
from tests.conftest import Env

ZERO_ID = "00000000-0000-4000-8000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[2]
EARTHQUAKE_SAMPLE = REPO_ROOT / "datasets" / "samples" / "earthquake_sample.csv"


def _body(dataset_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"dataset_id": dataset_id, "name": "Flood scenario A",
                            "depth_multiplier": 2.0, "rise_cm_per_hour": 0.0, "hours": 2}
    body.update(overrides)
    return body


def _create(env: Env, dataset_id: str, username: str = "analyst", **overrides: Any) -> Any:
    return env.api("POST", "/api/simulations", env.token(username), json=_body(dataset_id, **overrides))


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def test_analyst_creates_a_labelled_run(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _create(env, dataset_id)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["output"]["data_class"] == "SIMULATED_FACT"
    assert run["output"]["label"] == "Simulation — illustrative parameters"
    assert run["output"]["not_for_operational_use"] is True
    assert run["parameters"] == {"depth_multiplier": 2.0, "rise_cm_per_hour": 0.0, "hours": 2}
    assert run["peak"] == {"hour": 0, "affected_rows": 3}
    assert run["dataset"] == {"id": dataset_id, "name": "flood_incidents"}
    assert run["dataset_sha256"] and run["pack"]["sha256"] and run["simulator_version"]


def test_output_hash_matches_the_stored_output(env: Env) -> None:
    run = _create(env, env.approved_dataset()).json()
    assert sha256_bytes(engine.canonical_json(run["output"])) == run["output_sha256"]


def test_same_request_gives_the_same_output_hash(env: Env) -> None:
    dataset_id = env.approved_dataset()
    first = _create(env, dataset_id).json()
    second = _create(env, dataset_id).json()
    assert first["id"] != second["id"]
    assert first["output_sha256"] == second["output_sha256"]


def test_list_returns_summaries_without_output_and_no_usernames(env: Env) -> None:
    created = _create(env, env.approved_dataset()).json()
    response = env.api("GET", "/api/simulations", env.token("viewer"))
    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [created["id"]]
    assert "output" not in rows[0]
    assert "username" not in rows[0]["created_by"]
    assert "analyst" not in response.text


def test_get_returns_the_full_run_for_viewers(env: Env) -> None:
    created = _create(env, env.approved_dataset()).json()
    response = env.api("GET", f"/api/simulations/{created['id']}", env.token("viewer"))
    assert response.status_code == 200
    assert response.json()["output"]["timeline"][0]["hour"] == 0


def test_unknown_run_is_not_found(env: Env) -> None:
    response = env.api("GET", f"/api/simulations/{ZERO_ID}", env.token("viewer"))
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_viewer_cannot_create_a_run(env: Env) -> None:
    response = _create(env, env.approved_dataset(), username="viewer")
    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"


def test_unauthenticated_request_is_refused(env: Env) -> None:
    response = env.api("POST", "/api/simulations", None, json=_body(env.approved_dataset()))
    assert response.status_code == 401


def test_pending_dataset_is_not_found(env: Env) -> None:
    pending = env.upload("analyst").json()["id"]
    response = _create(env, pending)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_dataset_without_water_depth_is_refused(env: Env) -> None:
    dataset_id = env.upload("analyst", data=EARTHQUAKE_SAMPLE.read_bytes(),
                            filename="earthquake_sample.csv").json()["id"]
    assert env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer")).status_code == 200
    response = _create(env, dataset_id)
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_out_of_range_parameters_are_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    for overrides in ({"depth_multiplier": 0.0}, {"depth_multiplier": 3.5}, {"rise_cm_per_hour": -1},
                      {"rise_cm_per_hour": 101}, {"hours": 0}, {"hours": 73}, {"name": ""}):
        assert _create(env, dataset_id, **overrides).status_code == 422, overrides


def test_unknown_fields_are_refused(env: Env) -> None:
    body = _body(env.approved_dataset())
    body["seed"] = 7
    response = env.api("POST", "/api/simulations", env.token("analyst"), json=body)
    assert response.status_code == 422


def test_run_writes_one_audit_row_with_hashes_not_names(env: Env) -> None:
    run = _create(env, env.approved_dataset()).json()
    rows = [row for row in env.audit_rows() if row["action"] == "simulation.created"]
    assert len(rows) == 1
    assert rows[0]["subject"] == run["id"]
    assert rows[0]["detail"]["output_sha256"] == run["output_sha256"]
    assert "analyst" not in str(rows[0]["detail"])
