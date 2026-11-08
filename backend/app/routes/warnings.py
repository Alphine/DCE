"""Public warnings (docs/notes/w5-i18n.md): draft, human approval, withdrawal, and a public read.

Internal routes (/api/warnings) need a session or API key. Only the public route (/api/public/warnings) needs no
login, and it returns PUBLISHED rows with a fixed set of fields. Responses carry user IDs, never usernames.
Owner: include `router` with the other API routers in main.py.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import audit
from app.auth import CurrentUser, require_role
from app.clientip import resolve_client_ip
from app.container import services_of
from app.countries import country_filter, country_or_default, country_query, normalize_country
from app.errors import AppError
from app.ratelimit import SlidingWindowLimiter
from app.routes.reports import HazardType
from app.util import canonical_json, new_id, sha256_bytes, utc_now

router = APIRouter(tags=["warnings"])

Lang = Literal["en", "id"]
WarningStatus = Literal["DRAFT", "PUBLISHED", "WITHDRAWN"]
PUBLIC_LIMIT = 100
PUBLIC_RATE_PER_MINUTE = 120
_FORBIDDEN_MARKUP = ("<", ">")


def _plain_text(value: str, label: str, *, allow_newlines: bool) -> str:
    """Plain text only: no '<' or '>' and no control characters. Returns the stripped text."""
    for ch in value:
        if ch in _FORBIDDEN_MARKUP:
            raise ValueError(f"{label} cannot contain '<' or '>'.")
        if ord(ch) < 32 and not (allow_newlines and ch in "\n\t"):
            raise ValueError(f"{label} cannot contain control characters.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    return text


class WarningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    lang: Lang
    hazard_type: HazardType
    # Optional. NULL is shown as 'ID' in responses, like other country-scoped records.
    country_code: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _plain_text(value, "Title", allow_newlines=False)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _plain_text(value, "Body", allow_newlines=True)

    @field_validator("country_code")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return normalize_country(value)


class PublishBody(BaseModel):
    """The approver sends the content hash they reviewed. A different hash means the content changed."""

    model_config = ConfigDict(extra="forbid")
    content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


def content_sha256_of(title: str, body: str, lang: str, country_code: str | None, hazard_type: str) -> str:
    return sha256_bytes(canonical_json({
        "title": title, "body": body, "lang": lang, "country_code": country_code, "hazard_type": hazard_type,
    }).encode("utf-8"))


def _load(conn: sqlite3.Connection, warning_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM warnings WHERE id = ?", (warning_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Warning not found.")
    return row


def _public_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "lang": row["lang"],
        "country_code": country_or_default(row["country_code"]),
        "hazard_type": row["hazard_type"],
        "published_at": row["published_at"],
    }


def _internal_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        **_public_view(row),
        "status": row["status"],
        "content_sha256": row["content_sha256"],
        "created_by": row["created_by"],
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"],
        "withdrawn_at": row["withdrawn_at"],
        "created_at": row["created_at"],
    }


@router.post("/warnings", status_code=201)
def create_warning(body: WarningIn, request: Request,
                   user: CurrentUser = Depends(require_role("Analyst")),
                   ) -> JSONResponse:
    services = services_of(request)
    warning_id = new_id()
    sha = content_sha256_of(body.title, body.body, body.lang, body.country_code, body.hazard_type)
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO warnings (id, country_code, lang, hazard_type, title, body, status, content_sha256, "
            "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?)",
            (warning_id, body.country_code, body.lang, body.hazard_type, body.title, body.body, sha,
             user.id, utc_now()),
        )
        audit.append(conn, actor=user.username, action="warning.drafted", subject=warning_id, detail={
            "lang": body.lang, "hazard_type": body.hazard_type,
            "country_code": country_or_default(body.country_code), "content_sha256": sha,
        })
        view = _internal_view(_load(conn, warning_id))
    return JSONResponse(view, status_code=201)


@router.get("/warnings")
def list_warnings(request: Request,
                  status: WarningStatus | None = Query(default=None),
                  country: str | None = Query(default=None, max_length=2),
                  user: CurrentUser = Depends(require_role("Viewer")),
                  ) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[str] = []
    if status is not None:
        clauses.append("w.status = ?")
        params.append(status)
    frag, cparams = country_filter("w", country_query(country))
    if frag:
        clauses.append(frag)
        params += cparams
    where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
    with services_of(request).db.read() as conn:
        rows = conn.execute(f"SELECT * FROM warnings w {where}ORDER BY w.created_at DESC, w.id DESC LIMIT 200",
                            params).fetchall()
    return [_internal_view(r) for r in rows]


@router.post("/warnings/{warning_id}/publish")
def publish_warning(warning_id: str, body: PublishBody, request: Request,
                    user: CurrentUser = Depends(require_role("Approver")),
                    ) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, warning_id)
        if row["created_by"] == user.id:
            raise AppError("SELF_APPROVAL_NOT_ALLOWED", "You cannot publish a warning you drafted.")
        if row["status"] != "DRAFT":
            raise AppError("INVALID_STATE", f"A warning in {row['status']} cannot be published.")
        recomputed = content_sha256_of(row["title"], row["body"], row["lang"], row["country_code"],
                                       row["hazard_type"])
        if recomputed != row["content_sha256"] or body.content_sha256 != row["content_sha256"]:
            raise AppError("CONTENT_CHANGED", "The warning content no longer matches the hash you reviewed.",
                           status=409)
        duplicate = conn.execute(
            "SELECT 1 FROM warnings WHERE status = 'PUBLISHED' AND content_sha256 = ?",
            (row["content_sha256"],),
        ).fetchone()
        if duplicate is not None:
            raise AppError("CONFLICT", "An identical warning is already published.")
        now = utc_now()
        conn.execute(
            "UPDATE warnings SET status = 'PUBLISHED', decided_by = ?, decided_at = ?, published_at = ? "
            "WHERE id = ? AND status = 'DRAFT'",
            (user.id, now, now, warning_id),
        )
        audit.append(conn, actor=user.username, action="warning.published", subject=warning_id, detail={
            "role": user.role, "lang": row["lang"], "hazard_type": row["hazard_type"],
            "country_code": country_or_default(row["country_code"]), "content_sha256": row["content_sha256"],
        })
        view = _internal_view(_load(conn, warning_id))
    return view


@router.post("/warnings/{warning_id}/withdraw")
def withdraw_warning(warning_id: str, request: Request,
                     user: CurrentUser = Depends(require_role("Approver")),
                     ) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, warning_id)
        if row["status"] != "PUBLISHED":
            raise AppError("INVALID_STATE", f"A warning in {row['status']} cannot be withdrawn.")
        conn.execute(
            "UPDATE warnings SET status = 'WITHDRAWN', withdrawn_at = ? WHERE id = ? AND status = 'PUBLISHED'",
            (utc_now(), warning_id),
        )
        audit.append(conn, actor=user.username, action="warning.withdrawn", subject=warning_id, detail={
            "role": user.role, "content_sha256": row["content_sha256"],
        })
        view = _internal_view(_load(conn, warning_id))
    return view


def _public_limiter(request: Request) -> SlidingWindowLimiter:
    """One limiter per app instance, created on first use. Reuses app/ratelimit.py, keyed by client IP."""
    limiter = getattr(request.app.state, "public_warnings_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(PUBLIC_RATE_PER_MINUTE, 60.0)
        request.app.state.public_warnings_limiter = limiter
    return limiter


@router.get("/public/warnings")
def public_warnings(request: Request,
                    country: str | None = Query(default=None, max_length=2),
                    lang: Lang | None = Query(default=None),
                    ) -> JSONResponse:
    services = services_of(request)
    client_ip = resolve_client_ip(request.client.host if request.client else None,
                                  request.headers.get("x-forwarded-for"),
                                  services.settings.trusted_proxy_networks)
    if not _public_limiter(request).allow(client_ip):
        raise AppError("RATE_LIMITED", "Too many requests. Try again in a minute.", headers={"Retry-After": "60"})

    clauses = ["w.status = 'PUBLISHED'"]
    params: list[str] = []
    if lang is not None:
        clauses.append("w.lang = ?")
        params.append(lang)
    frag, cparams = country_filter("w", country_query(country))
    if frag:
        clauses.append(frag)
        params += cparams
    with services.db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM warnings w WHERE " + " AND ".join(clauses) +
            f" ORDER BY w.published_at DESC, w.id DESC LIMIT {PUBLIC_LIMIT}",
            params,
        ).fetchall()
    return JSONResponse([_public_view(r) for r in rows], headers={"Cache-Control": "public, max-age=60"})
