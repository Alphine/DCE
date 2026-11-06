"""Authentication routes: login, logout, current user (docs/api.md section 2)."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.auth import CurrentUser, current_user, expiry_timestamp
from app.container import services_of
from app.errors import AppError
from app.security import (DUMMY_PASSWORD_HASH, SESSION_COOKIE, SESSION_TTL_HOURS, new_session_token,
                          session_id_for, verify_password)
from app.util import utc_now

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
    client_ip = request.client.host if request.client else "unknown"
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


@router.post("/logout", status_code=204)
def logout(request: Request, user: CurrentUser = Depends(current_user)) -> Response:
    services = services_of(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    with services.db.transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id_for(token),))
        audit.append(conn, actor=user.username, action="auth.logout", subject=user.id, detail={})
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict",
                           secure=services.settings.cookie_secure)
    return response


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    return user.as_json()
