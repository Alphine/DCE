"""Admin user management (RBAC, last-Admin rule, audit) and API keys for automation (docs/api.md section 2)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import PASSWORD, SEED_USERS, Env

NEW_PASSWORD = "initial-passphrase-9"
NON_ADMIN_ROLES = ["viewer", "analyst", "reviewer", "approver"]


def _me(env: Env, username: str) -> dict[str, Any]:
    return env.api("GET", "/api/auth/me", env.token(username)).json()


def _user_id(env: Env, username: str) -> str:
    return _me(env, username)["id"]


def _create_user(env: Env, username: str, role: str, password: str = NEW_PASSWORD) -> str:
    response = env.api("POST", "/api/admin/users", env.token("admin"),
                       json={"username": username, "role": role, "password": password})
    assert response.status_code == 201, response.text
    env.login(username, password)  # also caches the session token for env.token(username)
    return response.json()["id"]


# --- RBAC: every admin route is Admin only --------------------------------------------------------------------

@pytest.mark.parametrize("username", NON_ADMIN_ROLES)
def test_non_admin_gets_403_on_user_routes(logged_in: Env, username: str) -> None:
    token = logged_in.token(username)
    assert logged_in.api("GET", "/api/admin/users", token).status_code == 403
    create = logged_in.api("POST", "/api/admin/users", token,
                           json={"username": "sneaky", "role": "Admin", "password": NEW_PASSWORD})
    assert create.status_code == 403
    assert create.json()["error"]["code"] == "FORBIDDEN"
    patch = logged_in.api("PATCH", f"/api/admin/users/{_user_id(logged_in, 'analyst')}", token,
                          json={"role": "Admin"})
    assert patch.status_code == 403


@pytest.mark.parametrize("username", NON_ADMIN_ROLES)
def test_non_admin_gets_403_on_api_key_routes(logged_in: Env, username: str) -> None:
    token = logged_in.token(username)
    assert logged_in.api("GET", "/api/admin/api-keys", token).status_code == 403
    assert logged_in.api("POST", "/api/admin/api-keys", token, json={}).status_code == 403


def test_list_users_returns_no_password_material(logged_in: Env) -> None:
    response = logged_in.api("GET", "/api/admin/users", logged_in.token("admin"))
    assert response.status_code == 200
    users = response.json()
    assert {u["username"] for u in users} >= set(SEED_USERS)
    assert all(set(u) == {"id", "username", "role", "status", "created_at"} for u in users)
    assert "scrypt$" not in response.text and "password" not in response.text


# --- User creation and updates --------------------------------------------------------------------------------

def test_create_user_logs_in_and_is_audited_without_password(logged_in: Env) -> None:
    user_id = _create_user(logged_in, "field.officer", "Analyst")
    assert logged_in.login("field.officer", NEW_PASSWORD)
    created = [r for r in logged_in.audit_rows() if r["action"] == "admin.user_created"]
    assert created[-1]["subject"] == user_id
    assert created[-1]["detail"] == {"role": "Analyst"}
    assert NEW_PASSWORD not in str(created[-1])


def test_create_user_validation_and_duplicates(logged_in: Env) -> None:
    admin = logged_in.token("admin")
    weak = logged_in.api("POST", "/api/admin/users", admin,
                         json={"username": "weak.user", "role": "Viewer", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "VALIDATION_FAILED"
    bad_role = logged_in.api("POST", "/api/admin/users", admin,
                             json={"username": "bad.role", "role": "Superuser", "password": NEW_PASSWORD})
    assert bad_role.status_code == 422
    extra = logged_in.api("POST", "/api/admin/users", admin,
                          json={"username": "extra.field", "role": "Viewer", "password": NEW_PASSWORD,
                                "status": "active"})
    assert extra.status_code == 422
    duplicate = logged_in.api("POST", "/api/admin/users", admin,
                              json={"username": "analyst", "role": "Viewer", "password": NEW_PASSWORD})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"


def test_role_change_takes_effect_on_next_request(logged_in: Env) -> None:
    analyst_id = _user_id(logged_in, "analyst")
    admin = logged_in.token("admin")
    response = logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", admin, json={"role": "Reviewer"})
    assert response.status_code == 200
    assert response.json()["role"] == "Reviewer"
    assert logged_in.api("GET", "/api/admin/users", logged_in.token("analyst")).status_code == 403
    changed = [r for r in logged_in.audit_rows() if r["action"] == "admin.user_role_changed"]
    assert changed[-1]["detail"] == {"from": "Analyst", "to": "Reviewer"}


def test_disable_revokes_sessions_and_blocks_login(logged_in: Env) -> None:
    analyst_id = _user_id(logged_in, "analyst")
    session = logged_in.token("analyst")
    response = logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", logged_in.token("admin"),
                             json={"disabled": True})
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert logged_in.api("GET", "/api/auth/me", session).status_code == 401
    blocked = logged_in.api("POST", "/api/auth/login", json={"username": "analyst", "password": PASSWORD})
    assert blocked.status_code == 401
    assert any(r["action"] == "admin.user_disabled" for r in logged_in.audit_rows())

    enabled = logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", logged_in.token("admin"),
                            json={"disabled": False})
    assert enabled.json()["status"] == "active"
    assert logged_in.login("analyst", PASSWORD)
    assert any(r["action"] == "admin.user_enabled" for r in logged_in.audit_rows())


def test_patch_requires_a_field_and_known_user(logged_in: Env) -> None:
    admin = logged_in.token("admin")
    empty = logged_in.api("PATCH", f"/api/admin/users/{_user_id(logged_in, 'analyst')}", admin, json={})
    assert empty.status_code == 422
    missing = logged_in.api("PATCH", "/api/admin/users/no-such-user", admin, json={"role": "Viewer"})
    assert missing.status_code == 404


# --- Last active Admin and self-protection --------------------------------------------------------------------

def test_admin_cannot_disable_themselves(logged_in: Env) -> None:
    admin_id = _user_id(logged_in, "admin")
    response = logged_in.api("PATCH", f"/api/admin/users/{admin_id}", logged_in.token("admin"),
                             json={"disabled": True})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_last_active_admin_cannot_be_demoted_or_disabled(logged_in: Env) -> None:
    admin = logged_in.token("admin")
    admin_id = _user_id(logged_in, "admin")
    demote = logged_in.api("PATCH", f"/api/admin/users/{admin_id}", admin, json={"role": "Viewer"})
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "CONFLICT"
    # A second Admin, but the seeded admin is still needed only while the second one is active.
    second_id = _create_user(logged_in, "second.admin", "Admin")
    assert logged_in.api("GET", "/api/admin/users", logged_in.token("second.admin")).status_code == 200
    # Now the seeded admin may step down, because another active Admin exists.
    step_down = logged_in.api("PATCH", f"/api/admin/users/{admin_id}", admin, json={"role": "Viewer"})
    assert step_down.status_code == 200
    # The remaining Admin is now the last one: it cannot be disabled by a session it does not own (see below)
    # and cannot be demoted by itself.
    second_token = logged_in.token("second.admin")
    last = logged_in.api("PATCH", f"/api/admin/users/{second_id}", second_token, json={"role": "Viewer"})
    assert last.status_code == 409
    assert last.json()["error"]["code"] == "CONFLICT"


def test_disabled_admin_does_not_count_towards_last_admin(logged_in: Env) -> None:
    # Create a second Admin, then disable it. The seeded admin is again the only active Admin.
    second_id = _create_user(logged_in, "standby.admin", "Admin")
    off = logged_in.api("PATCH", f"/api/admin/users/{second_id}", logged_in.token("admin"), json={"disabled": True})
    assert off.status_code == 200
    admin_id = _user_id(logged_in, "admin")
    response = logged_in.api("PATCH", f"/api/admin/users/{admin_id}", logged_in.token("admin"),
                             json={"role": "Viewer"})
    assert response.status_code == 409


def test_audit_chain_still_verifies_after_admin_changes(logged_in: Env) -> None:
    _create_user(logged_in, "chain.check", "Viewer")
    response = logged_in.api("POST", "/api/audit/verify", logged_in.token("admin"))
    assert response.status_code == 200
    assert response.json()["valid"] is True


# --- API keys ---------------------------------------------------------------------------------------------------

def _create_key(env: Env, owner_username: str | None = None, token: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if owner_username is not None:
        body["user_id"] = _user_id(env, owner_username)
    response = env.api("POST", "/api/admin/api-keys", token or env.token("admin"), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_key_works_and_is_shown_once(logged_in: Env) -> None:
    created = _create_key(logged_in)
    token = created["token"]
    assert token.startswith("dce_") and len(token) >= 32 + 4
    assert "note" in created

    me = logged_in.api("GET", "/api/auth/me", None, headers={"X-API-Key": token})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    listing = logged_in.api("GET", "/api/admin/api-keys", logged_in.token("admin"))
    assert listing.status_code == 200
    assert token not in listing.text
    assert "key_hash" not in listing.text
    assert all("token" not in k for k in listing.json())


def test_revoked_key_is_rejected_and_revoke_is_not_repeatable(logged_in: Env) -> None:
    created = _create_key(logged_in)
    key_id, token = created["id"], created["token"]
    admin = logged_in.token("admin")
    assert logged_in.api("GET", "/api/auth/me", None, headers={"X-API-Key": token}).status_code == 200

    revoke = logged_in.api("DELETE", f"/api/admin/api-keys/{key_id}", admin)
    assert revoke.status_code == 204
    rejected = logged_in.api("GET", "/api/auth/me", None, headers={"X-API-Key": token})
    assert rejected.status_code == 401
    assert logged_in.api("DELETE", f"/api/admin/api-keys/{key_id}", admin).status_code == 409
    assert logged_in.api("DELETE", "/api/admin/api-keys/unknown-id", admin).status_code == 404

    status = next(k for k in logged_in.api("GET", "/api/admin/api-keys", admin).json() if k["id"] == key_id)
    assert status["status"] == "revoked"
    actions = [r["action"] for r in logged_in.audit_rows()]
    assert "api_key.created" in actions and "api_key.revoked" in actions


def test_unknown_key_is_rejected(logged_in: Env) -> None:
    response = logged_in.api("GET", "/api/auth/me", None, headers={"X-API-Key": "dce_not-a-real-key"})
    assert response.status_code == 401


def test_token_is_never_stored_in_plaintext(logged_in: Env) -> None:
    created = _create_key(logged_in)
    token = created["token"]
    with logged_in.db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM api_keys").fetchall()]
    assert rows and all(token not in str(r) for r in rows)
    import hashlib
    assert rows[0]["key_hash"] == hashlib.sha256(token.encode()).hexdigest()

    # Scan every database file (including the WAL) for the token itself.
    for path in logged_in.settings.data_dir.glob("dce.sqlite3*"):
        assert token.encode() not in path.read_bytes(), path.name
    assert all(token not in str(r["detail"]) and token not in r["detail_json"] for r in logged_in.audit_rows())


def test_key_cannot_exceed_owner_role(logged_in: Env) -> None:
    key = _create_key(logged_in, "analyst")["token"]
    headers = {"X-API-Key": key}
    # Analyst owner: no Admin routes.
    assert logged_in.api("GET", "/api/admin/users", None, headers=headers).status_code == 403
    assert logged_in.api("GET", "/api/admin/api-keys", None, headers=headers).status_code == 401
    # Key management is session-only, so a key cannot mint more keys.
    minted = logged_in.api("POST", "/api/admin/api-keys", None, headers=headers, json={})
    assert minted.status_code == 401
    # The role is the owner's live role: promoting the owner widens the key, demoting narrows it again.
    analyst_id = _user_id(logged_in, "analyst")
    admin = logged_in.token("admin")
    logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", admin, json={"role": "Admin"})
    assert logged_in.api("GET", "/api/admin/users", None, headers=headers).status_code == 200
    logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", admin, json={"role": "Viewer"})
    assert logged_in.api("GET", "/api/admin/users", None, headers=headers).status_code == 403


def test_key_stops_working_when_owner_is_disabled(logged_in: Env) -> None:
    key = _create_key(logged_in, "analyst")["token"]
    analyst_id = _user_id(logged_in, "analyst")
    logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", logged_in.token("admin"), json={"disabled": True})
    assert logged_in.api("GET", "/api/auth/me", None, headers={"X-API-Key": key}).status_code == 401


def test_cannot_create_key_for_disabled_or_unknown_owner(logged_in: Env) -> None:
    admin = logged_in.token("admin")
    unknown = logged_in.api("POST", "/api/admin/api-keys", admin, json={"user_id": "nobody"})
    assert unknown.status_code == 404
    analyst_id = _user_id(logged_in, "analyst")
    logged_in.api("PATCH", f"/api/admin/users/{analyst_id}", admin, json={"disabled": True})
    disabled = logged_in.api("POST", "/api/admin/api-keys", admin, json={"user_id": analyst_id})
    assert disabled.status_code == 409


def test_api_key_usage_reaches_admin_routes_for_admin_owner(logged_in: Env) -> None:
    key = _create_key(logged_in)["token"]
    response = logged_in.api("GET", "/api/admin/users", None, headers={"X-API-Key": key})
    assert response.status_code == 200
