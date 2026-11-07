"""Structured report intake (SDD 10.7, 16.3, 23.5): roles, validation, null handling, review, and audit."""

from __future__ import annotations

from typing import Any

from tests.conftest import Env


def _valid(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "hazard_type": "FLOOD",
        "location_name": "Kemang",
        "latitude": -6.26,
        "longitude": 106.81,
        "observed_at": "2026-11-05T10:00:00Z",
        "reporter_role": "RESPONDER",
        "severity_reported": "HIGH",
        "source_reference": "radio-07",
        "notes": "Water above the curb on Jl. Kemang Raya.",
    }
    body.update(overrides)
    return body


def _create(env: Env, username: str = "analyst", **overrides: Any) -> dict[str, Any]:
    response = env.api("POST", "/api/reports", env.token(username), json=_valid(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _verify(env: Env, report_id: str, decision: str = "approve") -> dict[str, Any]:
    response = env.api("POST", f"/api/reports/{report_id}/review", env.token("reviewer"),
                       json={"decision": decision, "note": "checked against radio log"})
    assert response.status_code == 200, response.text
    return response.json()


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


# ----- roles -------------------------------------------------------------------------------------

def test_analyst_creates_report_and_viewer_cannot(env: Env) -> None:
    created = _create(env)
    assert created["status"] == "OBSERVATION"
    assert created["submitter"]["username"] == "analyst"
    assert created["review"] is None

    denied = env.api("POST", "/api/reports", env.token("viewer"), json=_valid())
    assert denied.status_code == 403
    assert _error_code(denied) == "FORBIDDEN"

    anonymous = env.api("POST", "/api/reports", None, json=_valid())
    assert anonymous.status_code == 401


def test_reporter_roles_above_analyst_may_submit(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("approver"), json=_valid())
    assert response.status_code == 201


# ----- validation --------------------------------------------------------------------------------

def test_unknown_hazard_type_is_rejected(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(hazard_type="VOLCANO"))
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_enum_fields_reject_values_outside_the_fixed_set(env: Env) -> None:
    for field, value in (("reporter_role", "JOURNALIST"), ("severity_reported", "EXTREME")):
        response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(**{field: value}))
        assert response.status_code == 422, field
        assert _error_code(response) == "VALIDATION_FAILED"


def test_latitude_and_longitude_must_be_finite_and_in_range(env: Env) -> None:
    cases = [{"latitude": 91.0, "longitude": 0.0}, {"latitude": 0.0, "longitude": 181.0},
             {"latitude": -90.5, "longitude": 0.0}]
    for overrides in cases:
        response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(**overrides))
        assert response.status_code == 422, overrides

    nan_body = b'{"hazard_type": "FLOOD", "latitude": NaN, "longitude": 106.8}'
    response = env.api("POST", "/api/reports", env.token("analyst"), content=nan_body,
                       headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_boolean_coordinates_are_rejected(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(latitude=True, longitude=1.0))
    assert response.status_code == 422


def test_one_coordinate_without_the_other_is_rejected(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(longitude=None))
    assert response.status_code == 422
    assert _error_code(response) == "VALIDATION_FAILED"


def test_text_lengths_and_control_characters_are_bounded(env: Env) -> None:
    too_long_notes = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(notes="x" * 2001))
    assert too_long_notes.status_code == 422
    too_long_name = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(location_name="x" * 121))
    assert too_long_name.status_code == 422
    control = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(location_name="Kemang\x00"))
    assert control.status_code == 422


def test_observed_at_must_have_timezone_and_not_be_in_the_future(env: Env) -> None:
    naive = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(observed_at="2026-11-05T10:00:00"))
    assert naive.status_code == 422
    future = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(observed_at="2099-01-01T00:00:00Z"))
    assert future.status_code == 422
    garbage = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(observed_at="yesterday"))
    assert garbage.status_code == 422


def test_observed_at_is_stored_in_utc(env: Env) -> None:
    created = _create(env, observed_at="2026-11-05T17:00:00+07:00")
    assert created["observed_at"] == "2026-11-05T10:00:00Z"


def test_unknown_fields_are_rejected(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("analyst"), json=_valid(status="VERIFIED_OBSERVATION"))
    assert response.status_code == 422


def test_unknown_values_are_stored_as_null_never_zero(env: Env) -> None:
    created = _create(env, location_name=None, latitude=None, longitude=None, observed_at=None,
                      reporter_role=None, severity_reported=None, source_reference=None, notes=None)
    assert created["location"] == {"name": None, "latitude": None, "longitude": None}
    assert created["observed_at"] is None
    assert created["reporter_role"] is None
    assert created["severity_reported"] is None
    assert created["source_reference"] is None
    assert created["notes"] is None


def test_named_place_without_coordinates_never_gets_coordinates(env: Env) -> None:
    created = _create(env, latitude=None, longitude=None, location_name="Menteng")
    assert created["location"] == {"name": "Menteng", "latitude": None, "longitude": None}


def test_zero_coordinates_are_real_values_when_given(env: Env) -> None:
    created = _create(env, latitude=0, longitude=0)
    assert created["location"]["latitude"] == 0.0
    assert created["location"]["longitude"] == 0.0


# ----- visibility --------------------------------------------------------------------------------

def test_viewer_sees_only_verified_reports(env: Env) -> None:
    pending = _create(env, location_name="Tebet")
    verified = _create(env, location_name="Cilandak")
    _verify(env, verified["id"])

    viewer_list = env.api("GET", "/api/reports", env.token("viewer")).json()
    assert [r["id"] for r in viewer_list] == [verified["id"]]

    analyst_list = env.api("GET", "/api/reports", env.token("analyst")).json()
    assert {r["id"] for r in analyst_list} == {pending["id"], verified["id"]}

    hidden = env.api("GET", f"/api/reports/{pending['id']}", env.token("viewer"))
    assert hidden.status_code == 404
    assert _error_code(hidden) == "NOT_FOUND"
    shown = env.api("GET", f"/api/reports/{verified['id']}", env.token("viewer"))
    assert shown.status_code == 200


def test_unknown_report_is_not_found(env: Env) -> None:
    response = env.api("GET", "/api/reports/00000000-0000-4000-8000-000000000000", env.token("analyst"))
    assert response.status_code == 404


# ----- review ------------------------------------------------------------------------------------

def test_reviewer_verifies_and_separation_of_duties_holds(env: Env) -> None:
    own = _create(env, username="reviewer")
    self_review = env.api("POST", f"/api/reports/{own['id']}/review", env.token("reviewer"),
                          json={"decision": "approve"})
    assert self_review.status_code == 403
    assert _error_code(self_review) == "SELF_APPROVAL_NOT_ALLOWED"

    report = _create(env, username="analyst")
    analyst_review = env.api("POST", f"/api/reports/{report['id']}/review", env.token("analyst"),
                             json={"decision": "approve"})
    assert analyst_review.status_code == 403
    assert _error_code(analyst_review) == "FORBIDDEN"

    verified = _verify(env, report["id"])
    assert verified["status"] == "VERIFIED_OBSERVATION"
    assert verified["review"]["reviewer"]["username"] == "reviewer"

    again = env.api("POST", f"/api/reports/{report['id']}/review", env.token("reviewer"),
                    json={"decision": "reject"})
    assert again.status_code == 409
    assert _error_code(again) == "INVALID_STATE"


def test_rejected_report_stays_hidden_from_viewers(env: Env) -> None:
    report = _create(env)
    rejected = _verify(env, report["id"], decision="reject")
    assert rejected["status"] == "REJECTED"
    assert env.api("GET", f"/api/reports/{report['id']}", env.token("viewer")).status_code == 404


# ----- audit -------------------------------------------------------------------------------------

def test_create_and_review_write_audit_records_without_free_text(env: Env) -> None:
    report = _create(env, notes="Secret field note about the bridge")
    _verify(env, report["id"])

    rows = env.audit_rows()
    submitted = [r for r in rows if r["action"] == "report.submitted"]
    reviewed = [r for r in rows if r["action"] == "report.reviewed"]
    assert len(submitted) == 1 and submitted[0]["subject"] == report["id"]
    assert submitted[0]["actor"] == "analyst"
    assert submitted[0]["detail"]["coordinates"] is True
    assert submitted[0]["detail"]["notes_sha256"] is not None
    assert len(reviewed) == 1 and reviewed[0]["actor"] == "reviewer"
    assert reviewed[0]["detail"]["decision"] == "approve"

    raw = repr(rows)
    assert "Secret field note" not in raw
    assert "radio log" not in raw  # review note is stored as a hash too


def test_failed_validation_writes_no_audit_record(env: Env) -> None:
    token = env.token("analyst")  # log in first so the login audit row is not counted
    before = len(env.audit_rows())
    response = env.api("POST", "/api/reports", token, json=_valid(hazard_type="VOLCANO"))
    assert response.status_code == 422
    assert len(env.audit_rows()) == before
