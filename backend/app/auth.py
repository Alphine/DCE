"""Session authentication and role checks (docs/api.md sections 1 and 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request

from app.db import Db
from app.errors import AppError
from app.security import API_KEY_HEADER, SESSION_COOKIE, SESSION_TTL_HOURS, api_key_hash, session_id_for

ROLES = ("Viewer", "Analyst", "Reviewer", "Approver", "Admin")
_RANK = {role: i for i, role in enumerate(ROLES)}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    username: str
    role: str

    @property
    def rank(self) -> int:
        return _RANK[self.role]

    def has_at_least(self, role: str) -> bool:
        return self.rank >= _RANK[role]

    def as_json(self) -> dict[str, str]:
        return {"id": self.id, "username": self.username, "role": self.role}


def db_of(request: Request) -> Db:
    return request.app.state.db


def load_session_user(db: Db, token: str | None) -> CurrentUser | None:
    if not token:
        return None
    with db.read() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, r.role, s.expires_at, u.status FROM sessions s "
            "JOIN users u ON u.id = s.user_id JOIN user_roles r ON r.user_id = u.id "
            "WHERE s.id = ?",
            (session_id_for(token),),
        ).fetchone()
    if row is None or row["status"] != "active":
        return None
    expires = datetime.strptime(row["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"])


def expiry_timestamp() -> str:
    return (datetime.now(UTC) + timedelta(hours=SESSION_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_api_key_user(db: Db, token: str | None) -> CurrentUser | None:
    """An API key acts as its owner. The role is read from the owner's current role, so a key never exceeds it."""
    if not token:
        return None
    with db.read() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, r.role, u.status, k.expires_at, k.revoked_at FROM api_keys k "
            "JOIN users u ON u.id = k.user_id JOIN user_roles r ON r.user_id = u.id "
            "WHERE k.key_hash = ?",
            (api_key_hash(token),),
        ).fetchone()
    if row is None or row["status"] != "active" or row["revoked_at"] is not None:
        return None
    if row["expires_at"] is not None:
        expires = datetime.strptime(row["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            return None
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"])


def current_user(request: Request) -> CurrentUser:
    """Session cookie first, then the X-API-Key header (automation). Both resolve to a live user and role."""
    db = db_of(request)
    user = load_session_user(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        user = load_api_key_user(db, request.headers.get(API_KEY_HEADER))
    if user is None:
        raise AppError("UNAUTHENTICATED", "Sign in required.")
    request.state.actor = user.username
    return user


def session_user(request: Request) -> CurrentUser:
    """Browser session only. Used by routes that must not be reachable with an API key (logout, password change,
    API key management): a leaked key cannot end or mint sessions or keys."""
    user = load_session_user(db_of(request), request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise AppError("UNAUTHENTICATED", "Sign in required.")
    request.state.actor = user.username
    return user


def require_session_role(min_role: str):  # noqa: ANN201 - FastAPI dependency factory
    if min_role not in _RANK:
        raise ValueError(min_role)

    def _dep(user: CurrentUser = Depends(session_user)) -> CurrentUser:
        if not user.has_at_least(min_role):
            raise AppError("FORBIDDEN", "Your role may not perform this action.")
        return user

    return _dep


def require_role(min_role: str):  # noqa: ANN201 - FastAPI dependency factory
    if min_role not in _RANK:
        raise ValueError(min_role)

    def _dep(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.has_at_least(min_role):
            raise AppError("FORBIDDEN", "Your role may not perform this action.")
        return user

    return _dep

