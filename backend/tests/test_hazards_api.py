"""Hazard rule results for approved CSV datasets (docs/api.md section 2): roles, approval, packs, integrity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.datasets import dataset_file
from app.rules.engine import load_default_pack
from tests.conftest import Env

ZERO_ID = "00000000-0000-4000-8000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[2]
EARTHQUAKE_SAMPLE = REPO_ROOT / "datasets" / "samples" / "earthquake_sample.csv"
TSUNAMI_CSV = (
    "area,magnitude,depth_km,coast_distance_km\n"
    "Pesisir Padang,7.2,30,45\n"
    "Pesisir Mentawai,5.9,20,8\n"
    "Pesisir Bengkulu,,25,38\n"
).encode("utf-8")
GEOJSON = (b'{"type":"FeatureCollection","features":[{"type":"Feature",'
           b'"geometry":{"type":"Point","coordinates":[106.8,-6.2]},"properties":{}}]}')


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def _approved_upload(env: Env, data: bytes, filename: str) -> str:
    dataset_id = env.upload("analyst", data=data, filename=filename).json()["id"]
    response = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert response.status_code == 200, response.text
    return dataset_id


def _hazards(env: Env, dataset_id: str, pack: str | None = None, username: str = "viewer") -> Any:
    params: dict[str, str] = {"dataset_id": dataset_id}
    if pack is not None:
        params["pack"] = pack
    return env.api("GET", "/api/hazards", env.token(username), params=params)


def test_viewer_reads_flood_result_with_rule_pack_and_dataset(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _hazards(env, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool"] == "hazard_analyzer"
    assert body["data_class"] == "INFERRED_FACT"
    assert body["rule_pack"]["sha256"] == load_default_pack()[1]["pack_sha256"]
    assert body["rows_evaluated"] == 6
    assert body["rows_unknown_depth"] == 1  # the Cilandak row has an empty depth
    assert body["dataset"] == {"id": dataset_id, "name": "flood_incidents"}


def test_default_pack_is_flood(env: Env) -> None:
    dataset_id = env.approved_dataset()
    assert _hazards(env, dataset_id).json()["tool"] == "hazard_analyzer"
    assert _hazards(env, dataset_id, pack="flood").json()["tool"] == "hazard_analyzer"


def test_pending_dataset_is_not_found(env: Env) -> None:
    pending = env.upload("analyst").json()["id"]
    response = _hazards(env, pending)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_unknown_dataset_is_not_found(env: Env) -> None:
    response = _hazards(env, ZERO_ID)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"


def test_unauthenticated_read_is_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = env.api("GET", "/api/hazards", None, params={"dataset_id": dataset_id})
    assert response.status_code == 401


def test_unknown_pack_is_refused(env: Env) -> None:
    dataset_id = env.approved_dataset()
    response = _hazards(env, dataset_id, pack="wildfire")
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_tsunami_pack_reads_earthquake_columns(env: Env) -> None:
    dataset_id = _approved_upload(env, TSUNAMI_CSV, "tsunami_scenario.csv")
    response = _hazards(env, dataset_id, pack="tsunami")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool"] == "tsunami_analyzer"
    assert body["rows_evaluated"] == 3
    assert body["dataset"]["id"] == dataset_id
    severities = {item["area"]: item["severity"] for item in body["results"]}
    assert severities["Pesisir Padang"] == "HIGH"
    assert severities["Pesisir Mentawai"] == "LOW"
    # The magnitude is unknown and no rule can be decided without it, so the row is UNKNOWN, never LOW.
    assert severities["Pesisir Bengkulu"] == "UNKNOWN"


def test_flood_pack_on_earthquake_sample_never_fails_with_a_server_error(env: Env) -> None:
    dataset_id = _approved_upload(env, EARTHQUAKE_SAMPLE.read_bytes(), "earthquake_sample.csv")
    response = _hazards(env, dataset_id, pack="flood")
    # The flood helper tolerates a missing depth column: every row is UNKNOWN, which is a clear result.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows_unknown_depth"] == body["rows_evaluated"]
    assert body["rows_evaluated"] > 0


def test_non_csv_dataset_is_refused(env: Env) -> None:
    dataset_id = _approved_upload(env, GEOJSON, "areas.geojson")
    response = _hazards(env, dataset_id)
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_tampered_file_on_disk_is_a_conflict(env: Env) -> None:
    dataset_id = env.approved_dataset()
    with env.db.read() as conn:
        storage_name = conn.execute("SELECT storage_name FROM datasets WHERE id = ?", (dataset_id,)).fetchone()[0]
    dataset_file(env.settings.data_dir, storage_name).write_bytes(b"district,water_depth_cm\nKemang,999\n")
    response = _hazards(env, dataset_id)
    assert response.status_code == 409
    assert _error_code(response) == "CONFLICT"


def test_missing_file_on_disk_is_not_found(env: Env) -> None:
    dataset_id = env.approved_dataset()
    with env.db.read() as conn:
        storage_name = conn.execute("SELECT storage_name FROM datasets WHERE id = ?", (dataset_id,)).fetchone()[0]
    dataset_file(env.settings.data_dir, storage_name).unlink()
    response = _hazards(env, dataset_id)
    assert response.status_code == 404
    assert _error_code(response) == "NOT_FOUND"
