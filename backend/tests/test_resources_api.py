"""Illustrative resource estimate (docs/api.md section 2): roles, approval, column checks, and the request body."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.conftest import Env

ZERO_ID = "00000000-0000-4000-8000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[2]
EARTHQUAKE_SAMPLE = REPO_ROOT / "datasets" / "samples" / "earthquake_sample.csv"


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _estimate(env: Env, dataset_id: str, username: str = "analyst", **overrides: Any) -> Any:
    body: dict[str, Any] = {"dataset_id": dataset_id, "pack": "flood"}
    body.update(overrides)
    return env.api("POST", "/api/resources/estimate", env.token(username), json=body)


def test_analyst_estimates_an_approved_flood_csv(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _estimate(env, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_class"] == "SIMULATED_FACT"
    assert body["label"] == "ILLUSTRATIVE ratios"
    assert body["tool"] == "resource_estimator"
    assert body["not_for_operational_use"] is True
    assert body["assumptions"] and all(isinstance(item, str) for item in body["assumptions"])
    assert body["inputs"]["rows_total"] == 6
    assert body["inputs"]["unknown_depth_rows"] == 1
    assert set(body["estimates"]) >= {"households_affected", "people_estimated", "water_packs",
                                      "food_packs", "shelter_kits", "drinking_water_litres_total"}
    assert body["rule_pack"]["sha256"]
    assert body["dataset"] == {"id": dataset_id, "name": "flood_incidents"}


def test_reviewer_and_admin_may_also_estimate(env: Env) -> None:
    dataset_id = env.approved_dataset()
    assert _estimate(env, dataset_id, username="reviewer").status_code == 200
    assert _estimate(env, dataset_id, username="admin").status_code == 200


def test_viewer_is_forbidden(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _estimate(env, dataset_id, username="viewer")
    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"


def test_unauthenticated_request_is_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = env.api("POST", "/api/resources/estimate", None, json={"dataset_id": dataset_id, "pack": "flood"})
    assert response.status_code == 401


def test_unknown_dataset_is_not_found(env: Env) -> None:
    response = _estimate(env, ZERO_ID)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_pending_dataset_is_not_found(env: Env) -> None:
    pending = env.upload("analyst").json()["id"]
    response = _estimate(env, pending)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_dataset_without_water_depth_is_refused(env: Env) -> None:
    dataset_id = env.upload("analyst", data=EARTHQUAKE_SAMPLE.read_bytes(),
                            filename="earthquake_sample.csv").json()["id"]
    assert env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer")).status_code == 200
    response = _estimate(env, dataset_id)
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_unsupported_pack_is_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _estimate(env, dataset_id, pack="tsunami")
    assert response.status_code == 422


def test_unknown_request_fields_are_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _estimate(env, dataset_id, people_per_household=99)
    assert response.status_code == 422
