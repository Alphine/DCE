"""Situation picture (docs/api.md section 2): verified reports and approved CSV coordinates only."""

from __future__ import annotations

from typing import Any

from tests.conftest import Env

COORDINATE_CSV = (
    "name,lat,lon\n"
    "Pos A,-6.2,106.8\n"
    "No coords,,\n"
    "Bad lat,95,106\n"
    "Pos B,-6.3,106.9\n"
).encode("utf-8")


def _report(env: Env, username: str = "analyst", **fields: Any) -> str:
    body: dict[str, Any] = {"hazard_type": "FLOOD", "location_name": "Kemang",
                            "latitude": -6.26, "longitude": 106.81}
    body.update(fields)
    response = env.api("POST", "/api/reports", env.token(username), json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _verify(env: Env, report_id: str) -> None:
    response = env.api("POST", f"/api/reports/{report_id}/review", env.token("reviewer"), json={"decision": "approve"})
    assert response.status_code == 200, response.text


def _situation(env: Env, params: dict[str, Any] | None = None, username: str = "viewer") -> Any:
    return env.api("GET", "/api/situation", env.token(username), params=params or {})


def _points(env: Env, **kwargs: Any) -> list[dict[str, Any]]:
    response = _situation(env, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["points"]


def test_verified_report_with_coordinates_appears_as_report(env: Env) -> None:
    report_id = _report(env)
    _verify(env, report_id)
    response = _situation(env)
    assert response.status_code == 200
    body = response.json()
    report_points = [p for p in body["points"] if p["kind"] == "REPORT"]
    assert len(report_points) == 1
    point = report_points[0]
    assert point["id"] == report_id
    assert point["label"] == "FLOOD · Kemang"
    assert point["lat"] == -6.26 and point["lon"] == 106.81
    assert point["status"] == "VERIFIED_OBSERVATION"
    assert point["data_class"] == "VERIFIED_OBSERVATION"
    assert body["counts"] == {"REPORT": 1, "DATASET_ROW": 0}
    assert body["truncated"] is False


def test_unnamed_place_gets_a_plain_label(env: Env) -> None:
    report_id = _report(env, location_name=None)
    _verify(env, report_id)
    point = _points(env)[0]
    assert point["label"] == "FLOOD · unnamed place"


def test_unverified_and_coordinate_less_reports_do_not_appear(env: Env) -> None:
    pending = _report(env)
    no_coordinates = _report(env, latitude=None, longitude=None)
    _verify(env, no_coordinates)
    ids = {p["id"] for p in _points(env)}
    assert pending not in ids
    assert no_coordinates not in ids


def test_approved_csv_rows_with_coordinates_appear_with_row_numbers(env: Env) -> None:
    dataset_id = env.upload("analyst", data=COORDINATE_CSV, filename="positions.csv").json()["id"]
    assert env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer")).status_code == 200

    rows = [p for p in _points(env) if p["kind"] == "DATASET_ROW"]
    assert [p["row"] for p in rows] == [1, 4]  # row 2 has no coordinates, row 3 has an invalid latitude
    assert [p["label"] for p in rows] == ["Pos A", "Pos B"]
    assert rows[0]["lat"] == -6.2 and rows[0]["lon"] == 106.8
    assert all(p["dataset_id"] == dataset_id and p["dataset_name"] == "positions" for p in rows)
    assert all(p["data_class"] is None for p in rows)


def test_pending_dataset_rows_do_not_appear(env: Env) -> None:
    pending = env.upload("analyst", data=COORDINATE_CSV, filename="positions.csv").json()["id"]
    assert not [p for p in _points(env) if p.get("dataset_id") == pending]


def test_csv_without_lat_lon_columns_contributes_nothing(env: Env) -> None:
    env.approved_dataset()  # the flood sample has district and depth, no lat or lon
    assert [p for p in _points(env) if p["kind"] == "DATASET_ROW"] == []


def test_limit_truncates_and_sets_truncated(env: Env) -> None:
    for _ in range(3):
        _verify(env, _report(env))

    limited = _situation(env, {"limit": 2})
    assert limited.status_code == 200
    body = limited.json()
    assert len(body["points"]) == 2
    assert body["counts"] == {"REPORT": 2, "DATASET_ROW": 0}
    assert body["truncated"] is True

    exact = _situation(env, {"limit": 3}).json()
    assert len(exact["points"]) == 3
    assert exact["truncated"] is False


def test_limit_bounds_are_enforced(env: Env) -> None:
    assert _situation(env, {"limit": 0}).status_code == 422
    assert _situation(env, {"limit": 2001}).status_code == 422


def test_unauthenticated_request_is_refused(env: Env) -> None:
    response = env.api("GET", "/api/situation", None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_analyst_sees_the_same_verified_points_as_viewer(env: Env) -> None:
    _verify(env, _report(env))
    viewer = _points(env, username="viewer")
    analyst = _points(env, username="analyst")
    assert [p["id"] for p in viewer] == [p["id"] for p in analyst]
