"""Admin routes: user management and API keys (docs/api.md section 2, Admin only).

Every change is written to the audit log in the same transaction. Passwords, password hashes and API key tokens
never reach the audit log, a response (other than the one-time token at creation), or a log line.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app import audit
from app.auth import CurrentUser, require_role, require_session_role
from app.container import services_of
from app.errors import AppError
from app.security import PASSWORD_MAX_LENGTH, api_key_hash, hash_password, new_api_key_token, password_policy_error
from app.util import new_id, utc_now

router = APIRouter(prefix="/admin", tags=["admin"])

Role = Literal["Viewer", "Analyst", "Reviewer", "Approver", "Admin"]
API_KEY_SCOPE = "automation"  # the key acts with its owner's role; the scope column records the purpose


class CreateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,64}$")
    role: Role
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


EMAIL_PATTERN = r"(?i)^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$"  # stored lowercase


class UpdateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    disabled: StrictBool | None = None  # strict: "yes" or 1 is a 422, not a disable
    # Sent as null, the email is cleared. Not sent at all, it is left unchanged.
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)


class SetPasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class CreateApiKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, min_length=1, max_length=64)  # owner; defaults to the caller


def _user_json(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "role": row["role"], "email": row["email"],
            "status": row["status"], "created_at": row["created_at"]}


def _load_user(conn: Any, user_id: str) -> Any:
    return conn.execute(
        "SELECT u.id, u.username, u.email, u.status, u.created_at, r.role FROM users u "
        "JOIN user_roles r ON r.user_id = u.id WHERE u.id = ?", (user_id,)).fetchone()


# --- Users -----------------------------------------------------------------------------------------------------

@router.get("/users")
def list_users(request: Request, user: CurrentUser = Depends(require_role("Admin"))) -> list[dict[str, Any]]:
    with services_of(request).db.read() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.email, u.status, u.created_at, r.role FROM users u "
            "JOIN user_roles r ON r.user_id = u.id ORDER BY u.created_at, u.username").fetchall()
    return [_user_json(r) for r in rows]


@router.post("/users", status_code=201)
def create_user(body: CreateUserBody, request: Request,
                user: CurrentUser = Depends(require_role("Admin"))) -> dict[str, Any]:
    message = password_policy_error(body.password)
    if message is not None:
        raise AppError("VALIDATION_FAILED", message)
    password_hash = hash_password(body.password)  # outside the write transaction: scrypt is slow
    user_id = new_id()
    created_at = utc_now()
    with services_of(request).db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone() is not None:
            raise AppError("CONFLICT", "That username is already taken.")
        conn.execute("INSERT INTO users (id, username, password_hash, status, created_at) "
                     "VALUES (?, ?, ?, 'active', ?)", (user_id, body.username, password_hash, created_at))
        conn.execute("INSERT INTO user_roles (user_id, role) VALUES (?, ?)", (user_id, body.role))
        audit.append(conn, actor=user.username, action="admin.user_created", subject=user_id,
                     detail={"role": body.role})
        row = _load_user(conn, user_id)
    return _user_json(row)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UpdateUserBody, request: Request,
                user: CurrentUser = Depends(require_role("Admin"))) -> dict[str, Any]:
    email_given = "email" in body.model_fields_set
    if body.role is None and body.disabled is None and not email_given:
        raise AppError("VALIDATION_FAILED", "Provide role, disabled, or email.")
    services = services_of(request)
    with services.db.transaction() as conn:  # BEGIN IMMEDIATE: the last-Admin count cannot race
        target = _load_user(conn, user_id)
        if target is None:
            raise AppError("NOT_FOUND", "User not found.")
        if email_given:
            new_email = body.email.lower() if body.email else None
            if new_email != target["email"]:
                taken = conn.execute("SELECT 1 FROM users WHERE email = ? AND id != ?",
                                     (new_email, user_id)).fetchone() if new_email else None
                if taken is not None:
                    raise AppError("CONFLICT", "That email is already used by another account.")
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (new_email, user_id))
                audit.append(conn, actor=user.username, action="admin.user_email_changed", subject=user_id,
                             detail={"cleared": new_email is None})
        new_role = body.role or target["role"]
        if body.disabled is None:
            new_status = target["status"]
        else:
            new_status = "disabled" if body.disabled else "active"

        if new_status == "disabled" and target["id"] == user.id:
            raise AppError("FORBIDDEN", "You cannot disable your own account.")
        was_active_admin = target["role"] == "Admin" and target["status"] == "active"
        stays_active_admin = new_role == "Admin" and new_status == "active"
        if was_active_admin and not stays_active_admin:
            others = conn.execute(
                "SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id = u.id "
                "WHERE r.role = 'Admin' AND u.status = 'active' AND u.id != ?", (user_id,)).fetchone()[0]
            if others == 0:
                raise AppError("CONFLICT", "Cannot disable or demote the last active Admin.")

        if new_role != target["role"]:
            conn.execute("UPDATE user_roles SET role = ? WHERE user_id = ?", (new_role, user_id))
            audit.append(conn, actor=user.username, action="admin.user_role_changed", subject=user_id,
                         detail={"from": target["role"], "to": new_role})
        if new_status != target["status"]:
            conn.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
            if new_status == "disabled":
                revoked = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount
                audit.append(conn, actor=user.username, action="admin.user_disabled", subject=user_id,
                             detail={"sessions_revoked": revoked})
            else:
                audit.append(conn, actor=user.username, action="admin.user_enabled", subject=user_id, detail={})
        row = _load_user(conn, user_id)
    return _user_json(row)


@router.post("/users/{user_id}/password", status_code=204)
def set_user_password(user_id: str, body: SetPasswordBody, request: Request,
                      user: CurrentUser = Depends(require_role("Admin"))) -> Response:
    """Admin sets a new password for another account (or their own). Every session of that account is revoked.

    Use this to recover an account without email. Tell the person the new password through a safe channel and
    ask them to change it at once. The password is never written to the audit log or to a response."""
    message = password_policy_error(body.new_password)
    if message is not None:
        raise AppError("VALIDATION_FAILED", message)
    password_hash = hash_password(body.new_password)  # outside the write transaction: scrypt is slow
    with services_of(request).db.transaction() as conn:
        target = _load_user(conn, user_id)
        if target is None:
            raise AppError("NOT_FOUND", "User not found.")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        revoked = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount
        audit.append(conn, actor=user.username, action="admin.user_password_set", subject=user_id,
                     detail={"sessions_revoked": revoked})
    return Response(status_code=204)


# --- API keys (session login only; see auth.session_user) -------------------------------------------------------

def _key_json(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "owner": {"id": row["user_id"], "username": row["username"]},
            "role": row["role"], "scope": row["scope"], "status": "revoked" if row["revoked_at"] else "active",
            "created_at": row["created_at"], "expires_at": row["expires_at"], "revoked_at": row["revoked_at"]}


_KEY_SELECT = ("SELECT k.id, k.user_id, k.scope, k.created_at, k.expires_at, k.revoked_at, u.username, r.role "
               "FROM api_keys k JOIN users u ON u.id = k.user_id JOIN user_roles r ON r.user_id = k.user_id ")


@router.get("/api-keys")
def list_api_keys(request: Request, user: CurrentUser = Depends(require_session_role("Admin"))) -> list[dict[str, Any]]:
    with services_of(request).db.read() as conn:
        rows = conn.execute(_KEY_SELECT + "ORDER BY k.created_at, k.id").fetchall()
    return [_key_json(r) for r in rows]


@router.post("/api-keys", status_code=201)
def create_api_key(request: Request, body: CreateApiKeyBody | None = None,
                   user: CurrentUser = Depends(require_session_role("Admin"))) -> dict[str, Any]:
    # The body is optional (docs/api.md section 13): no body means the caller owns the key.
    owner_id = (body.user_id if body is not None else None) or user.id
    token = new_api_key_token()  # shown once in this response; only the hash is stored
    key_id = new_id()
    created_at = utc_now()
    with services_of(request).db.transaction() as conn:
        owner = _load_user(conn, owner_id)
        if owner is None:
            raise AppError("NOT_FOUND", "Owner user not found.")
        if owner["status"] != "active":
            raise AppError("CONFLICT", "The owner account is disabled.")
        conn.execute("INSERT INTO api_keys (id, user_id, key_hash, scope, expires_at, created_at, revoked_at) "
                     "VALUES (?, ?, ?, ?, NULL, ?, NULL)",
                     (key_id, owner_id, api_key_hash(token), API_KEY_SCOPE, created_at))
        audit.append(conn, actor=user.username, action="api_key.created", subject=key_id,
                     detail={"owner_id": owner_id, "role": owner["role"]})
        row = conn.execute(_KEY_SELECT + "WHERE k.id = ?", (key_id,)).fetchone()
    body_json = _key_json(row)
    body_json["token"] = token
    body_json["note"] = "Store this token now. It is shown once and cannot be retrieved later."
    return body_json


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: str, request: Request,
                   user: CurrentUser = Depends(require_session_role("Admin"))) -> Response:
    with services_of(request).db.transaction() as conn:
        row = conn.execute("SELECT user_id, revoked_at FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "API key not found.")
        if row["revoked_at"] is not None:
            raise AppError("CONFLICT", "API key is already revoked.")
        conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?", (utc_now(), key_id))
        audit.append(conn, actor=user.username, action="api_key.revoked", subject=key_id,
                     detail={"owner_id": row["user_id"]})
    return Response(status_code=204)
