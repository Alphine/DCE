"""Regressions found by the API audit (docs/audit/api.md): each test pins one bug that once returned a 500 or a
wrong status code. Kept separate so the audit trail stays readable."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from tests.conftest import Env


def _user_id(env: Env, username: str) -> str:
    users = env.api("GET", "/api/admin/users", env.token("admin")).json()
    return next(u["id"] for u in users if u["username"] == username)


def _report_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"hazard_type": "FLOOD", "location_name": "Kemang", "latitude": -6.26,
                            "longitude": 106.81, "observed_at": "2026-11-05T10:00:00Z"}
    body.update(overrides)
    return body


# ----- observed_at outside the representable range used to raise OverflowError (HTTP 500) ----------------

def test_report_observed_at_before_year_one_in_utc_is_422(env: Env) -> None:
    # 0001-01-01 00:00 at +14:00 is still year 0 in UTC, which datetime cannot represent.
    response = env.api("POST", "/api/reports", env.token("analyst"),
                       json=_report_body(observed_at="0001-01-01T00:00:00+14:00"))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_report_observed_at_after_year_9999_in_utc_is_422(env: Env) -> None:
    response = env.api("POST", "/api/reports", env.token("analyst"),
                       json=_report_body(observed_at="9999-12-31T23:59:59-23:59"))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_sync_report_with_out_of_range_observed_at_is_rejected_not_internal(env: Env) -> None:
    item = {"op_id": str(uuid.uuid4()), "kind": "REPORT_CREATE",
            "payload": _report_body(observed_at="0001-01-01T00:00:00+14:00"),
            "made_at": datetime.now(UTC).isoformat()}
    response = env.api("POST", "/api/sync/batch", env.token("analyst"), json={"client_id": "device-1", "items": [item]})
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "REJECTED"
    assert result["code"] == "VALIDATION_FAILED"


# ----- audit offset beyond SQLite's 64-bit range used to raise an overflow (HTTP 500) --------------------

def test_audit_huge_offset_is_422_not_500(env: Env) -> None:
    token = env.token("reviewer")
    response = env.api("GET", "/api/audit?offset=999999999999999999999", token)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_audit_normal_paging_still_works(env: Env) -> None:
    response = env.api("GET", "/api/audit?limit=5&offset=0", env.token("reviewer"))
    assert response.status_code == 200
    assert "items" in response.json()


# ----- POST /api/admin/api-keys: the body is optional (docs/api.md section 13) -----------------------------

def test_api_key_without_body_is_owned_by_the_caller(env: Env) -> None:
    admin_token = env.token("admin")
    me = env.api("GET", "/api/auth/me", admin_token).json()
    response = env.api("POST", "/api/admin/api-keys", admin_token)  # no body at all
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["owner"]["id"] == me["id"]
    assert body["token"].startswith("dce_")


def test_api_key_with_empty_object_body_is_owned_by_the_caller(env: Env) -> None:
    admin_token = env.token("admin")
    response = env.api("POST", "/api/admin/api-keys", admin_token, json={})
    assert response.status_code == 201, response.text


def test_api_key_for_unknown_owner_is_404(env: Env) -> None:
    response = env.api("POST", "/api/admin/api-keys", env.token("admin"), json={"user_id": str(uuid.uuid4())})
    assert response.status_code == 404


# ----- PATCH /api/admin/users/{id}: "disabled" is a real boolean, so "yes" or 1 must not disable -------

def test_disabled_must_be_a_json_boolean(env: Env) -> None:
    admin_token = env.token("admin")
    target = _user_id(env, "analyst")
    for value in ("yes", 1, "true", "off"):
        response = env.api("PATCH", f"/api/admin/users/{target}", admin_token, json={"disabled": value})
        assert response.status_code == 422, (value, response.text)
    users = env.api("GET", "/api/admin/users", admin_token).json()
    analyst = next(u for u in users if u["username"] == "analyst")
    assert analyst["status"] == "active"


def test_disabled_boolean_still_disables_and_enables(env: Env) -> None:
    admin_token = env.token("admin")
    target = _user_id(env, "viewer")
    off = env.api("PATCH", f"/api/admin/users/{target}", admin_token, json={"disabled": True})
    assert off.status_code == 200, off.text
    on = env.api("PATCH", f"/api/admin/users/{target}", admin_token, json={"disabled": False})
    assert on.status_code == 200, on.text
