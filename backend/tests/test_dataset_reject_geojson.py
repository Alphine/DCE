"""Dataset rejection (POST /api/datasets/{id}/reject) and GeoJSON upload, profile, and validation."""

from __future__ import annotations

import json

import pytest

from app.datasets import MAX_UPLOAD_BYTES
from tests.conftest import Env

GEO_OK = json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [106.82, -6.20]},
     "properties": {"name": "Depot A", "capacity": 10, "status": None}},
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[106.80, -6.21], [106.83, -6.22]]},
     "properties": {"name": "Road X", "blocked": True}},
    {"type": "Feature", "geometry": {"type": "Polygon",
                                     "coordinates": [[[106.7, -6.3], [106.9, -6.3], [106.9, -6.1], [106.7, -6.3]]]},
     "properties": None},
    {"type": "Feature", "geometry": None, "properties": {"name": "No geometry"}},
]}).encode("utf-8")


def _fc(features: list) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode("utf-8")


# ----- reject -------------------------------------------------------------------------------------------

def test_reject_sets_status_blocks_agent_and_cannot_be_approved(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.upload("analyst").json()["id"]
    response = env.api("POST", f"/api/datasets/{dataset_id}/reject", env.token("reviewer"),
                       json={"note": "Source not verified"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REJECTED"

    task = env.api("POST", "/api/agent/tasks", env.token("analyst"), json={
        "instruction": "Count flooded districts.", "dataset_id": dataset_id,
        "requested_outputs": ["situation_report"]})
    assert task.status_code == 403
    assert task.json()["error"]["code"] == "FORBIDDEN"

    again = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE"
    twice = env.api("POST", f"/api/datasets/{dataset_id}/reject", env.token("reviewer"))
    assert twice.status_code == 409


def test_reject_rules_match_approve(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.upload("analyst").json()["id"]
    # Analyst is below Reviewer.
    assert env.api("POST", f"/api/datasets/{dataset_id}/reject", env.token("analyst")).status_code == 403
    # A Reviewer may not reject their own upload.
    own = env.upload("reviewer").json()["id"]
    response = env.api("POST", f"/api/datasets/{own}/reject", env.token("reviewer"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_NOT_ALLOWED"
    # Unknown dataset and an over-long note.
    assert env.api("POST", "/api/datasets/00000000-0000-4000-8000-000000000000/reject",
                   env.token("reviewer")).status_code == 404
    too_long = env.api("POST", f"/api/datasets/{dataset_id}/reject", env.token("reviewer"),
                       json={"note": "x" * 501})
    assert too_long.status_code == 422
    # Still pending after the refused attempts.
    detail = env.api("GET", f"/api/datasets/{dataset_id}", env.token("analyst")).json()
    assert detail["status"] == "PENDING_VALIDATION"


def test_reject_without_body_and_audit_record(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.upload("analyst").json()["id"]
    response = env.api("POST", f"/api/datasets/{dataset_id}/reject", env.token("reviewer"))
    assert response.status_code == 200
    rejected = [row for row in env.audit_rows() if row["action"] == "dataset.rejected"]
    assert len(rejected) == 1
    assert rejected[0]["subject"] == dataset_id
    assert rejected[0]["detail"]["note_sha256"] is None
    assert "Source not verified" not in json.dumps(env.audit_rows())


# ----- GeoJSON upload -----------------------------------------------------------------------------------

def test_geojson_upload_profile_and_storage(logged_in: Env) -> None:
    env = logged_in
    response = env.upload("analyst", data=GEO_OK, filename="zones.geojson")
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["kind"] == "GEOJSON"
    assert view["status"] == "PENDING_VALIDATION"
    profile = view["profile"]
    assert profile["feature_count"] == 4
    assert profile["geometry_types"] == {"LineString": 1, "Point": 1, "Polygon": 1, "null": 1}
    assert {p["name"]: p["present"] for p in profile["property_keys"]} == {
        "blocked": 1, "capacity": 1, "name": 3, "status": 0}
    assert len(profile["preview"]) == 4
    stored = env.settings.data_dir / "datasets" / f"{view['id']}.geojson"
    assert stored.is_file()
    # Rows are a CSV concept.
    rows = env.api("GET", f"/api/datasets/{view['id']}/rows", env.token("analyst"))
    assert rows.status_code == 422


def test_csv_upload_is_kind_csv(logged_in: Env) -> None:
    view = logged_in.upload("analyst").json()
    assert view["kind"] == "CSV"
    assert view["profile"]["rows"] == 6


def test_json_that_is_not_geojson_is_refused(logged_in: Env) -> None:
    response = logged_in.upload("analyst", data=b'{"hello": "world"}', filename="plain.json")
    assert response.status_code == 422
    assert "FeatureCollection" in response.json()["error"]["message"]


@pytest.mark.parametrize("label,data", [
    ("empty", b""),
    ("not json", b"{"),
    ("nul byte", b'{"type":"FeatureCollection","features":[]}\x00'),
    ("not utf8", b"\xff\xfe{}"),
    ("not a collection", b'{"type":"Feature","geometry":null,"properties":{}}'),
    ("no features", _fc([])),
    ("nan coordinate", b'{"type":"FeatureCollection","features":[{"type":"Feature",'
                       b'"geometry":{"type":"Point","coordinates":[NaN,1]},"properties":{}}]}'),
    ("point with one number", _fc([{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1]},
                                    "properties": {}}])),
    ("polygon too shallow", _fc([{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [1.0, 2.0]},
                                  "properties": {}}])),
    ("unknown geometry type", _fc([{"type": "Feature", "geometry": {"type": "Circle", "coordinates": [1, 2]},
                                    "properties": {}}])),
    ("feature without geometry member", _fc([{"type": "Feature", "properties": {}}])),
    ("bad properties", _fc([{"type": "Feature", "geometry": None, "properties": [1]}])),
    ("nested geometry collection", _fc([{"type": "Feature", "geometry": {
        "type": "GeometryCollection", "geometries": [{"type": "GeometryCollection", "geometries": []}]},
        "properties": {}}])),
])
def test_geojson_structural_rejections(logged_in: Env, label: str, data: bytes) -> None:
    response = logged_in.upload("analyst", data=data, filename="bad.geojson")
    assert response.status_code == 422, (label, response.text)
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_geojson_size_limit(logged_in: Env) -> None:
    big = b" " * (MAX_UPLOAD_BYTES + 1)
    response = logged_in.upload("analyst", data=big, filename="huge.geojson")
    assert response.status_code == 413


def test_geojson_approval_flow_keeps_status_rules(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.upload("analyst", data=GEO_OK, filename="zones.geojson").json()["id"]
    assert env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("analyst")).status_code == 403
    approved = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert approved.status_code == 200
    assert approved.json()["kind"] == "GEOJSON"
