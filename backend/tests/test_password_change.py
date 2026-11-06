"""POST /api/auth/password: self-service password change (docs/api.md section 2)."""

from __future__ import annotations

from tests.conftest import PASSWORD, Env

NEW_PASSWORD = "brand-new-passphrase-2"


def _change(env: Env, token: str, current: str, new: str) -> object:
    return env.api("POST", "/api/auth/password", token,
                   json={"current_password": current, "new_password": new})


def test_wrong_current_password_is_refused_and_audited(logged_in: Env) -> None:
    token = logged_in.token("analyst")
    response = _change(logged_in, token, "not-the-password", NEW_PASSWORD)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    failed = [r for r in logged_in.audit_rows() if r["action"] == "auth.password_change_failed"]
    assert failed, "a failed password change must be audited"
    assert "not-the-password" not in str(failed[-1]) and PASSWORD not in str(failed[-1])
    # Nothing changed: the old password still works.
    assert logged_in.login("analyst", PASSWORD)


def test_new_password_must_meet_policy(logged_in: Env) -> None:
    token = logged_in.token("analyst")
    short = _change(logged_in, token, PASSWORD, "short-pw-1")
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "VALIDATION_FAILED"
    long = _change(logged_in, token, PASSWORD, "x" * 257)
    assert long.status_code == 422


def test_new_password_must_differ_from_current(logged_in: Env) -> None:
    response = _change(logged_in, logged_in.token("analyst"), PASSWORD, PASSWORD)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_unknown_body_fields_are_rejected(logged_in: Env) -> None:
    response = logged_in.api("POST", "/api/auth/password", logged_in.token("analyst"),
                             json={"current_password": PASSWORD, "new_password": NEW_PASSWORD, "role": "Admin"})
    assert response.status_code == 422


def test_change_updates_password_and_revokes_other_sessions(logged_in: Env) -> None:
    current = logged_in.token("analyst")
    other = logged_in.login("analyst", PASSWORD)  # a second browser session for the same user
    response = _change(logged_in, current, PASSWORD, NEW_PASSWORD)
    assert response.status_code == 204

    assert logged_in.api("GET", "/api/auth/me", current).status_code == 200  # the current session survives
    assert logged_in.api("GET", "/api/auth/me", other).status_code == 401    # the other session is revoked

    old_login = logged_in.api("POST", "/api/auth/login", json={"username": "analyst", "password": PASSWORD})
    assert old_login.status_code == 401
    new_login = logged_in.api("POST", "/api/auth/login", json={"username": "analyst", "password": NEW_PASSWORD})
    assert new_login.status_code == 200


def test_change_audit_entry_has_no_password(logged_in: Env) -> None:
    _change(logged_in, logged_in.token("analyst"), PASSWORD, NEW_PASSWORD)
    changed = [r for r in logged_in.audit_rows() if r["action"] == "auth.password_changed"]
    assert len(changed) == 1
    assert changed[0]["detail"]["other_sessions_revoked"] >= 0
    dump = str(changed[0])
    assert PASSWORD not in dump and NEW_PASSWORD not in dump


def test_password_change_needs_a_session_and_an_api_key_cannot_use_it(logged_in: Env) -> None:
    assert logged_in.api("POST", "/api/auth/password", None,
                         json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 401
    key = _create_key(logged_in, "analyst")
    response = logged_in.api("POST", "/api/auth/password", None, headers={"X-API-Key": key},
                             json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert response.status_code == 401
    assert logged_in.login("analyst", PASSWORD)  # unchanged


def test_logout_with_api_key_does_not_end_the_browser_session(logged_in: Env) -> None:
    session = logged_in.token("analyst")
    key = _create_key(logged_in, "analyst")
    response = logged_in.api("POST", "/api/auth/logout", session, headers={"X-API-Key": key})
    assert response.status_code == 204  # the cookie session is the one that is ended
    assert logged_in.api("GET", "/api/auth/me", session).status_code == 401

    session2 = logged_in.login("analyst", PASSWORD)
    rejected = logged_in.api("POST", "/api/auth/logout", None, headers={"X-API-Key": key})
    assert rejected.status_code == 401  # a key alone cannot log out
    assert logged_in.api("GET", "/api/auth/me", session2).status_code == 200


def _create_key(env: Env, username: str) -> str:
    """Helper: an Admin creates a key owned by `username`. Returns the one-time token."""
    owner_id = env.api("GET", "/api/auth/me", env.token(username)).json()["id"]
    response = env.api("POST", "/api/admin/api-keys", env.token("admin"), json={"user_id": owner_id})
    assert response.status_code == 201, response.text
    return response.json()["token"]
