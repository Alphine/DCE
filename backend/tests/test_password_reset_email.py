"""Password reset by emailed link: no account enumeration, single use, expiry, disabled accounts, mail failures."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.mailer import MailError
from tests.conftest import PASSWORD, Env

NEW_PASSWORD = "fresh-reset-pass-2026"
GENERIC = "If an account with that email exists, a reset link has been sent. The link expires in 30 minutes."
TOKEN_RE = re.compile(r"#/reset\?token=([A-Za-z0-9_\-]+)")


@dataclass
class RecordingMailer:
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailError("The email could not be sent.")
        self.sent.append((to, subject, body))


def _setup(env: Env, email: str = "analyst@example.com") -> tuple[RecordingMailer, str]:
    mailer = RecordingMailer()
    env.app.state.services.mailer = mailer
    uid = next(u["id"] for u in env.api("GET", "/api/admin/users", env.token("admin")).json()
               if u["username"] == "analyst")
    response = env.api("PATCH", f"/api/admin/users/{uid}", env.token("admin"), json={"email": email})
    assert response.status_code == 200, response.text
    return mailer, uid


def _forgot(env: Env, email: str) -> Any:
    return env.api("POST", "/api/auth/forgot", None, json={"email": email})


def _token_from(mailer: RecordingMailer) -> str:
    match = TOKEN_RE.search(mailer.sent[-1][2])
    assert match, "reset link not found in the email"
    return match.group(1)


def _reset(env: Env, token: str, password: str = NEW_PASSWORD) -> Any:
    return env.api("POST", "/api/auth/reset", None, json={"token": token, "new_password": password})


def test_known_email_gets_a_link_and_the_link_sets_a_new_password(env: Env) -> None:
    mailer, _ = _setup(env)
    old_token = env.login("analyst")

    response = _forgot(env, "Analyst@Example.com")
    assert response.status_code == 202
    assert response.json()["detail"] == GENERIC
    assert [m[0] for m in mailer.sent] == ["analyst@example.com"]

    token = _token_from(mailer)
    assert _reset(env, token).status_code == 204

    assert env.api("GET", "/api/auth/me", old_token).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": PASSWORD}).status_code == 401
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": NEW_PASSWORD}).status_code == 200


def test_the_same_link_works_only_once(env: Env) -> None:
    mailer, _ = _setup(env)
    _forgot(env, "analyst@example.com")
    token = _token_from(mailer)
    assert _reset(env, token).status_code == 204
    again = _reset(env, token, NEW_PASSWORD + "x")
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "VALIDATION_FAILED"


def test_unknown_email_gets_the_same_answer_and_no_mail(env: Env) -> None:
    mailer, _ = _setup(env)
    response = _forgot(env, "nobody@example.com")
    assert response.status_code == 202
    assert response.json()["detail"] == GENERIC
    assert mailer.sent == []


def test_disabled_account_gets_no_mail(env: Env) -> None:
    mailer, uid = _setup(env)
    env.api("PATCH", f"/api/admin/users/{uid}", env.token("admin"), json={"disabled": True})
    _forgot(env, "analyst@example.com")
    assert mailer.sent == []


def test_expired_link_is_refused(env: Env) -> None:
    mailer, _ = _setup(env)
    _forgot(env, "analyst@example.com")
    token = _token_from(mailer)
    with env.db.transaction() as conn:
        conn.execute("UPDATE password_resets SET expires_at = '2000-01-01T00:00:00Z'")
    response = _reset(env, token)
    assert response.status_code == 422
    assert env.api("POST", "/api/auth/login", None,
                   json={"username": "analyst", "password": PASSWORD}).status_code == 200


def test_weak_password_does_not_use_up_the_link(env: Env) -> None:
    mailer, _ = _setup(env)
    _forgot(env, "analyst@example.com")
    token = _token_from(mailer)
    assert _reset(env, token, "short").status_code == 422
    assert _reset(env, token).status_code == 204


def test_asking_again_invalidates_the_older_link(env: Env) -> None:
    mailer, _ = _setup(env)
    _forgot(env, "analyst@example.com")
    first = _token_from(mailer)
    _forgot(env, "analyst@example.com")
    second = _token_from(mailer)
    assert _reset(env, first).status_code == 422
    assert _reset(env, second).status_code == 204


def test_mail_failure_still_answers_generically_and_is_audited(env: Env) -> None:
    mailer, _ = _setup(env)
    mailer.fail = True
    response = _forgot(env, "analyst@example.com")
    assert response.status_code == 202
    assert response.json()["detail"] == GENERIC
    assert [r["action"] for r in env.audit_rows()].count("auth.password_reset_mail_failed") == 1


def test_no_mailer_configured_answers_generically_and_sends_nothing(env: Env) -> None:
    _setup(env)
    env.app.state.services.mailer = None
    response = _forgot(env, "analyst@example.com")
    assert response.status_code == 202
    assert response.json()["detail"] == GENERIC


def test_token_is_stored_only_as_a_hash(env: Env) -> None:
    mailer, _ = _setup(env)
    _forgot(env, "analyst@example.com")
    token = _token_from(mailer)
    with env.db.read() as conn:
        stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM password_resets").fetchall()]
    assert stored and token not in stored and all(len(s) == 64 for s in stored)


def test_me_returns_the_account_email(env: Env) -> None:
    _setup(env)
    body = env.api("GET", "/api/auth/me", env.token("analyst")).json()
    assert body["email"] == "analyst@example.com"
    assert body["username"] == "analyst"
