"""Admin user page API: set or clear email, set a user's password, and the access rules around both."""

from __future__ import annotations

from typing import Any

from tests.conftest import PASSWORD, Env

NEW_PASSWORD = "admin-set-pass-2026"


def _user_id(env: Env, username: str) -> str:
    users = env.api("GET", "/api/admin/users", env.token("admin")).json()
    return next(u["id"] for u in users if u["username"] == username)


def _patch(env: Env, user_id: str, body: dict[str, Any], who: str = "admin") -> Any:
    return env.api("PATCH", f"/api/admin/users/{user_id}", env.token(who), json=body)


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def test_admin_sets_email_in_lowercase_and_it_is_listed(env: Env) -> None:
    uid = _user_id(env, "analyst")
    response = _patch(env, uid, {"email": "Analyst@Example.COM"})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "analyst@example.com"
    listed = next(u for u in env.api("GET", "/api/admin/users", env.token("admin")).json() if u["id"] == uid)
    assert listed["email"] == "analyst@example.com"


def test_email_can_be_cleared_with_null(env: Env) -> None:
    uid = _user_id(env, "viewer")
    _patch(env, uid, {"email": "viewer@example.com"})
    response = _patch(env, uid, {"email": None})
    assert response.status_code == 200
    assert response.json()["email"] is None


def test_email_change_leaves_role_alone(env: Env) -> None:
    uid = _user_id(env, "reviewer")
    response = _patch(env, uid, {"email": "reviewer@example.com"})
    assert response.json()["role"] == "Reviewer"


def test_invalid_email_is_refused(env: Env) -> None:
    uid = _user_id(env, "analyst")
    for bad in ("not-an-email", "a@b", "x y@example.com", "a" * 250 + "@example.com"):
        assert _patch(env, uid, {"email": bad}).status_code == 422, bad


def test_duplicate_email_is_a_conflict(env: Env) -> None:
    _patch(env, _user_id(env, "analyst"), {"email": "same@example.com"})
    response = _patch(env, _user_id(env, "viewer"), {"email": "SAME@example.com"})
    assert response.status_code == 409
    assert _error_code(response) == "CONFLICT"


def test_empty_patch_is_still_refused(env: Env) -> None:
    response = _patch(env, _user_id(env, "analyst"), {})
    assert response.status_code == 422


def test_non_admin_cannot_set_email_or_password(env: Env) -> None:
    uid = _user_id(env, "viewer")
    assert _patch(env, uid, {"email": "x@example.com"}, who="analyst").status_code == 403
    response = env.api("POST", f"/api/admin/users/{uid}/password", env.token("analyst"),
                       json={"new_password": NEW_PASSWORD})
    assert response.status_code == 403


def test_admin_sets_password_and_old_sessions_stop_working(env: Env) -> None:
    uid = _user_id(env, "analyst")
    old_token = env.login("analyst")
    assert env.api("GET", "/api/auth/me", old_token).status_code == 200

    response = env.api("POST", f"/api/admin/users/{uid}/password", env.token("admin"),
                       json={"new_password": NEW_PASSWORD})
    assert response.status_code == 204, response.text

    assert env.api("GET", "/api/auth/me", old_token).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": PASSWORD}).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": NEW_PASSWORD}).status_code == 200


def test_password_set_by_admin_is_audited_without_the_password(env: Env) -> None:
    uid = _user_id(env, "viewer")
    env.api("POST", f"/api/admin/users/{uid}/password", env.token("admin"), json={"new_password": NEW_PASSWORD})
    rows = [row for row in env.audit_rows() if row["action"] == "admin.user_password_set"]
    assert len(rows) == 1
    assert rows[0]["actor"] == "admin"
    assert NEW_PASSWORD not in str(rows[0])


def test_weak_or_unknown_target_is_refused(env: Env) -> None:
    uid = _user_id(env, "viewer")
    weak = env.api("POST", f"/api/admin/users/{uid}/password", env.token("admin"), json={"new_password": "short"})
    assert weak.status_code == 422
    missing = env.api("POST", "/api/admin/users/00000000-0000-4000-8000-000000000000/password",
                      env.token("admin"), json={"new_password": NEW_PASSWORD})
    assert missing.status_code == 404
