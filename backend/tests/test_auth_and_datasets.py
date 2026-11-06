"""Authentication, roles, rate limits, security headers, and dataset upload and approval."""

from __future__ import annotations

from typing import Callable

from app.security import SESSION_COOKIE
from tests.conftest import CSV_GOOD, PASSWORD, Env


def test_health_is_public_and_minimal(env: Env) -> None:
    response = env.api("GET", "/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_headers_and_request_id(env: Env) -> None:
    response = env.api("GET", "/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "unpkg.com" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"].startswith("req_")


def test_unauthenticated_request_gets_error_shape(env: Env) -> None:
    response = env.api("GET", "/api/datasets")
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"].startswith("req_")
    assert "Traceback" not in response.text


def test_unknown_api_route_uses_error_shape(env: Env) -> None:
    response = env.api("GET", "/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_login_sets_hardened_cookie_and_me_returns_user(env: Env) -> None:
    response = env.api("POST", "/api/auth/login", json={"username": "analyst", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"id": response.json()["id"], "username": "analyst", "role": "Analyst"}
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "path=/" in cookie_header
    assert "secure" not in cookie_header  # DCE_COOKIE_SECURE defaults to false
    token = response.cookies[SESSION_COOKIE]
    me = env.api("GET", "/api/auth/me", token)
    assert me.json()["username"] == "analyst"
    assert me.json()["role"] == "Analyst"


def test_wrong_password_is_refused_and_audited_without_password(env: Env) -> None:
    response = env.api("POST", "/api/auth/login", json={"username": "analyst", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    failed = [r for r in env.audit_rows() if r["action"] == "auth.login_failed"]
    assert failed, "failed login must be audited"
    assert "wrong-password" not in str(failed[-1])
    assert PASSWORD not in str(failed[-1])


def test_logout_ends_the_session(env: Env) -> None:
    token = env.login("viewer")
    assert env.api("GET", "/api/auth/me", token).status_code == 200
    response = env.api("POST", "/api/auth/logout", token)
    assert response.status_code == 204
    assert env.api("GET", "/api/auth/me", token).status_code == 401


def test_login_is_rate_limited_per_ip(make_env: Callable[..., Env]) -> None:
    env = make_env()
    for _ in range(10):
        env.api("POST", "/api/auth/login", json={"username": "admin", "password": "nope-nope-nope"})
    response = env.api("POST", "/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_viewer_cannot_upload(logged_in: Env) -> None:
    response = logged_in.upload("viewer")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_analyst_upload_profile(logged_in: Env) -> None:
    response = logged_in.upload("analyst", name="Flood sample")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Flood sample"
    assert body["status"] == "PENDING_VALIDATION"
    assert body["owner"]["username"] == "analyst"
    profile = body["profile"]
    assert profile["rows"] == 6
    dtypes = {c["name"]: c["dtype"] for c in profile["columns"]}
    assert dtypes["water_depth_cm"] == "integer"
    assert dtypes["road_status"] == "string"
    nulls = {c["name"]: c["nulls"] for c in profile["columns"]}
    assert nulls["water_depth_cm"] == 1
    assert nulls["affected_population"] == 1
    assert len(profile["preview"]) == 5
    assert profile["preview"][0] == {"district": "Kemang", "water_depth_cm": 35, "road_status": "blocked",
                                     "affected_population": 120, "reported_at": "2026-11-05T10:00:00Z"}


def test_stored_file_uses_server_generated_name(logged_in: Env) -> None:
    dataset_id = logged_in.upload("analyst", filename="../../evil name.csv").json()["id"]
    stored = list((logged_in.settings.data_dir / "datasets").glob("*.csv"))
    assert [p.name for p in stored] == [f"{dataset_id}.csv"]
    assert stored[0].read_bytes() == CSV_GOOD


def test_upload_validation_rules(logged_in: Env) -> None:
    cases = {
        "not a csv": (b"a,b\n1,2\n", "notes.txt"),
        "empty": (b"", "empty.csv"),
        "no header rows": (b"\n\n", "blank.csv"),
        "bad utf8": (b"name\n\xff\xfe\n", "latin.csv"),
        "ragged row": (b"a,b\n1,2\n3\n", "ragged.csv"),
        "duplicate header": (b"a,a\n1,2\n", "dup.csv"),
        "nul byte": (b"a,b\n1,\x002\n", "nul.csv"),
    }
    for label, (data, filename) in cases.items():
        response = logged_in.upload("analyst", data=data, filename=filename)
        assert response.status_code == 422, label
        assert response.json()["error"]["code"] == "VALIDATION_FAILED", label


def test_upload_size_limit(logged_in: Env) -> None:
    header = b"a,b\n"
    big = header + b"1,2\n" * (3 * 1024 * 1024)
    assert len(big) > 10 * 1024 * 1024
    response = logged_in.upload("analyst", data=big, filename="big.csv")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_analyst_cannot_approve_and_reviewer_can(logged_in: Env) -> None:
    dataset_id = logged_in.upload("analyst").json()["id"]
    analyst_try = logged_in.api("POST", f"/api/datasets/{dataset_id}/approve", logged_in.token("analyst"))
    assert analyst_try.status_code == 403
    assert analyst_try.json()["error"]["code"] == "FORBIDDEN"

    approved = logged_in.api("POST", f"/api/datasets/{dataset_id}/approve", logged_in.token("reviewer"))
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["owner"]["username"] == "analyst"


def test_self_approval_is_refused(logged_in: Env) -> None:
    # Approver ranks above Analyst, so it may upload and passes the role check; the self check refuses it.
    dataset_id = logged_in.upload("approver").json()["id"]
    response = logged_in.api("POST", f"/api/datasets/{dataset_id}/approve", logged_in.token("approver"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_NOT_ALLOWED"
