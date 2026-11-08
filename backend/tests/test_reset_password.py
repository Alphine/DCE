"""Operator password reset (app.reset_password): new password works, old one and sessions stop working, audited."""

from __future__ import annotations

import io

from app import reset_password
from tests.conftest import PASSWORD, Env

NEW_PASSWORD = "operator-reset-pass-2026"


def _run(env: Env, username: str, stdin_text: str) -> int:
    return reset_password.main([username], settings=env.settings, stdin=io.StringIO(stdin_text))


def test_reset_replaces_password_and_revokes_sessions(env: Env) -> None:
    old_token = env.login("analyst")
    assert env.api("GET", "/api/auth/me", old_token).status_code == 200

    assert _run(env, "analyst", NEW_PASSWORD + "\n") == 0

    assert env.api("GET", "/api/auth/me", old_token).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": PASSWORD}).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": NEW_PASSWORD}).status_code == 200


def test_reset_writes_one_operator_audit_row_without_the_password(env: Env) -> None:
    _run(env, "viewer", NEW_PASSWORD + "\n")
    rows = [row for row in env.audit_rows() if row["action"] == "auth.password_reset_by_operator"]
    assert len(rows) == 1
    assert rows[0]["actor"] == "operator"
    assert NEW_PASSWORD not in str(rows[0])
    assert PASSWORD not in str(rows[0])


def test_other_accounts_are_not_touched(env: Env) -> None:
    _run(env, "admin", NEW_PASSWORD + "\n")
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "viewer", "password": PASSWORD}).status_code == 200


def test_weak_password_is_refused_and_nothing_changes(env: Env) -> None:
    assert _run(env, "analyst", "short\n") == 1
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": PASSWORD}).status_code == 200


def test_unknown_user_is_refused(env: Env) -> None:
    assert _run(env, "nobody", NEW_PASSWORD + "\n") == 1


def test_same_password_is_refused(env: Env) -> None:
    assert _run(env, "analyst", PASSWORD + "\n") == 1


def _run_role(env: Env, username: str, role: str) -> int:
    return reset_password.main([username, "--role", role], settings=env.settings,
                               stdin=io.StringIO(NEW_PASSWORD + "\n"))


def _role_of(env: Env, username: str) -> str:
    token = env.login(username, NEW_PASSWORD)
    return env.api("GET", "/api/auth/me", token).json()["role"]


def test_role_creates_a_new_account_with_that_role(env: Env) -> None:
    code = reset_password.main(["demo-judge", "--role", "Viewer"], settings=env.settings,
                               stdin=io.StringIO(NEW_PASSWORD + "\n"))
    assert code == 0
    assert _role_of(env, "demo-judge") == "Viewer"
    created = [row for row in env.audit_rows() if row["action"] == "auth.user_created_by_operator"]
    assert len(created) == 1 and created[0]["detail"] == {"role": "Viewer"}


def test_role_on_an_existing_user_changes_the_role_and_is_audited(env: Env) -> None:
    assert _run_role(env, "viewer", "Analyst") == 0
    assert _role_of(env, "viewer") == "Analyst"
    changed = [row for row in env.audit_rows() if row["action"] == "admin.user_role_changed"]
    assert len(changed) == 1
    assert changed[0]["detail"] == {"from": "Viewer", "to": "Analyst"}
    assert changed[0]["actor"] == "operator"


def test_role_matching_the_current_role_changes_nothing_but_the_password(env: Env) -> None:
    assert _run_role(env, "analyst", "Analyst") == 0
    assert not [row for row in env.audit_rows() if row["action"] == "admin.user_role_changed"]


def test_the_last_active_admin_cannot_be_demoted(env: Env) -> None:
    assert _run_role(env, "admin", "Viewer") == 1
    # Refused as a whole: the password did not change either.
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "admin", "password": PASSWORD}).status_code == 200


def test_unknown_role_is_refused(env: Env) -> None:
    assert _run_role(env, "analyst", "Superuser") == 1


def test_missing_user_without_role_is_refused(env: Env) -> None:
    assert _run(env, "ghost", NEW_PASSWORD + "\n") == 1


def test_missing_username_or_password_is_a_usage_error(env: Env) -> None:
    assert reset_password.main([], settings=env.settings, stdin=io.StringIO("")) == 2
    assert _run(env, "analyst", "") == 2
