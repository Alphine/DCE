"""Authentication routes: login, logout, current user (docs/api.md section 2)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.auth import CurrentUser, current_user, expiry_timestamp, session_user
from app.clientip import resolve_client_ip
from app.container import services_of
from app.errors import AppError
from app.mailer import MailError
from app.security import (DUMMY_PASSWORD_HASH, PASSWORD_MAX_LENGTH, SESSION_COOKIE, SESSION_TTL_HOURS,
                          hash_password, new_session_token, password_policy_error, session_id_for,
                          verify_password)
from app.util import new_id, utc_now


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="strict",
        path="/",
        secure=services_of(request).settings.cookie_secure,
    )


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, str]:
    services = services_of(request)
    client_ip = resolve_client_ip(request.client.host if request.client else None,
                                  request.headers.get("x-forwarded-for"),
                                  services.settings.trusted_proxy_networks)
    if not services.login_limiter.allow(client_ip):
        raise AppError("RATE_LIMITED", "Too many login attempts. Try again in a minute.",
                       headers={"Retry-After": "60"})

    with services.db.read() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, u.password_hash, u.status, r.role FROM users u "
            "JOIN user_roles r ON r.user_id = u.id WHERE u.username = ?",
            (body.username,),
        ).fetchone()
    stored_hash = row["password_hash"] if row else DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, stored_hash)
    if row is None or not password_ok or row["status"] != "active":
        with services.db.transaction() as conn:
            audit.append(conn, actor="anonymous", action="auth.login_failed", subject=None, detail={
                "username_sha256": hashlib.sha256(body.username.encode("utf-8")).hexdigest(),
            })
        raise AppError("UNAUTHENTICATED", "Invalid username or password.")

    token = new_session_token()
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id_for(token), row["id"], utc_now(), expiry_timestamp()),
        )
        audit.append(conn, actor=row["username"], action="auth.login", subject=row["id"], detail={})
    _set_session_cookie(response, request, token)
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


class PasswordChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


@router.post("/logout", status_code=204)
def logout(request: Request, user: CurrentUser = Depends(session_user)) -> Response:
    services = services_of(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    with services.db.transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id_for(token),))
        audit.append(conn, actor=user.username, action="auth.logout", subject=user.id, detail={})
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict",
                           secure=services.settings.cookie_secure)
    return response


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeBody, request: Request,
                    user: CurrentUser = Depends(session_user)) -> Response:
    """Any signed-in user changes their own password. Browser session only. Every other session is revoked."""
    services = services_of(request)
    with services.db.read() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None:
        raise AppError("UNAUTHENTICATED", "Sign in required.")
    if not verify_password(body.current_password, row["password_hash"]):
        with services.db.transaction() as conn:  # its own write, so the audit row survives the 403
            audit.append(conn, actor=user.username, action="auth.password_change_failed", subject=user.id, detail={})
        raise AppError("FORBIDDEN", "Current password is incorrect.")
    message = password_policy_error(body.new_password)
    if message is not None:
        raise AppError("VALIDATION_FAILED", message)
    if verify_password(body.new_password, row["password_hash"]):
        raise AppError("VALIDATION_FAILED", "New password must differ from the current password.")

    new_hash = hash_password(body.new_password)
    current_session = session_id_for(request.cookies.get(SESSION_COOKIE, ""))
    with services.db.transaction() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user.id))
        revoked = conn.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?",
                               (user.id, current_session)).rowcount
        audit.append(conn, actor=user.username, action="auth.password_changed", subject=user.id,
                     detail={"other_sessions_revoked": revoked})
    return Response(status_code=204)


@router.get("/me")
def me(request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        row = conn.execute("SELECT email FROM users WHERE id = ?", (user.id,)).fetchone()
    return {**user.as_json(), "email": row["email"] if row else None}


# --- Password reset by email -------------------------------------------------------------------------------------

RESET_TTL_MINUTES = 30
GENERIC_ANSWER = "If an account with that email exists, a reset link has been sent. The link expires in 30 minutes."


class ForgotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)


class ResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _reset_email(link: str) -> str:
    return (
        "Someone asked to reset the password for your Disaster Commander Edge account.\n\n"
        f"Open this link to choose a new password (valid for {RESET_TTL_MINUTES} minutes, one use):\n{link}\n\n"
        "If you did not ask for this, ignore this email. Your password does not change.\n"
    )


@router.post("/forgot", status_code=202)
def forgot_password(body: ForgotBody, request: Request) -> dict[str, str]:
    """Email a reset link. The answer is the same whether or not the address belongs to an account."""
    services = services_of(request)
    client_ip = resolve_client_ip(request.client.host if request.client else None,
                                  request.headers.get("x-forwarded-for"),
                                  services.settings.trusted_proxy_networks)
    if not services.login_limiter.allow(f"forgot:{client_ip}"):
        raise AppError("RATE_LIMITED", "Too many requests. Try again in a minute.",
                       headers={"Retry-After": "60"})
    if services.mailer is None:
        return {"detail": GENERIC_ANSWER}

    email = body.email.strip().lower()
    token = secrets.token_urlsafe(32)
    now = utc_now()
    expires = (datetime.now(UTC) + timedelta(minutes=RESET_TTL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with services.db.transaction() as conn:
        row = conn.execute("SELECT id, username, status FROM users WHERE email = ?", (email,)).fetchone()
        if row is None or row["status"] != "active":
            return {"detail": GENERIC_ANSWER}
        conn.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                     (now, row["id"]))
        conn.execute("INSERT INTO password_resets (id, user_id, token_hash, expires_at, used_at, created_at) "
                     "VALUES (?, ?, ?, ?, NULL, ?)", (new_id(), row["id"], _token_hash(token), expires, now))
        audit.append(conn, actor=row["username"], action="auth.password_reset_requested", subject=row["id"],
                     detail={})
        user_id = row["id"]

    link = f"{services.settings.public_base_url.rstrip('/')}/#/reset?token={token}"
    try:
        services.mailer.send(email, "Reset your Disaster Commander Edge password", _reset_email(link))
    except MailError:
        with services.db.transaction() as conn:
            audit.append(conn, actor="system", action="auth.password_reset_mail_failed", subject=user_id,
                         detail={})
    return {"detail": GENERIC_ANSWER}


@router.post("/reset", status_code=204)
def reset_password(body: ResetBody, request: Request) -> Response:
    """Set a new password with an emailed link. The link works once, and all sessions of the account end."""
    message = password_policy_error(body.new_password)
    if message is not None:
        raise AppError("VALIDATION_FAILED", message)
    services = services_of(request)
    new_hash = hash_password(body.new_password)  # outside the write transaction: scrypt is slow
    now = utc_now()
    with services.db.transaction() as conn:
        row = conn.execute(
            "SELECT pr.id, pr.user_id, u.username FROM password_resets pr "
            "JOIN users u ON u.id = pr.user_id "
            "WHERE pr.token_hash = ? AND pr.used_at IS NULL AND pr.expires_at > ? AND u.status = 'active'",
            (_token_hash(body.token), now)).fetchone()
        if row is None:
            raise AppError("VALIDATION_FAILED", "This reset link is invalid or has expired. Ask for a new one.")
        conn.execute("UPDATE password_resets SET used_at = ? WHERE id = ?", (now, row["id"]))
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["user_id"]))
        revoked = conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],)).rowcount
        audit.append(conn, actor=row["username"], action="auth.password_reset_completed", subject=row["user_id"],
                     detail={"sessions_revoked": revoked})
    return Response(status_code=204)
