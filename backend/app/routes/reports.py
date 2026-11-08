"""Structured report intake (SDD 10.7) and human review (SDD 16.3): docs/api.md section 2.

A report enters as OBSERVATION once it passes validation. A Reviewer (not the submitter) promotes it to
VERIFIED_OBSERVATION or rejects it. Only VERIFIED_OBSERVATION reports are visible to Viewers.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import alerts as alerts_core
from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.countries import country_filter, country_or_default, country_query, normalize_country
from app.errors import AppError
from app.util import canonical_json, new_id, sha256_bytes, utc_now

router = APIRouter(prefix="/reports", tags=["reports"])

HazardType = Literal["EARTHQUAKE", "TSUNAMI", "EXTREME_RAINFALL", "FLOOD", "LANDSLIDE", "WILDFIRE", "SMOKE"]
ReporterRole = Literal["CIVILIAN", "VOLUNTEER", "OFFICIAL", "RESPONDER", "OTHER"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

MAX_FUTURE_SKEW = timedelta(minutes=5)

# The fields a reviewer reads. The content hash covers exactly these (docs/offline-global.md section 2).
_CONTENT_FIELDS = ("hazard_type", "location_name", "latitude", "longitude", "observed_at", "reporter_role",
                   "severity_reported", "source_reference", "notes")


def _clean_text(value: str | None, *, allow_newlines: bool = False) -> str | None:
    """Trim, turn an empty string into null, and refuse control characters."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for ch in text:
        if ord(ch) < 32 and not (allow_newlines and ch in "\n\t"):
            raise ValueError("Control characters are not allowed.")
    return text


class ReportIn(BaseModel):
    """Structured intake form (SDD 10.7). Every unknown field is sent as null."""

    model_config = ConfigDict(extra="forbid")

    hazard_type: HazardType
    location_name: str | None = Field(default=None, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    observed_at: str | None = Field(default=None, max_length=40)
    reporter_role: ReporterRole | None = None
    severity_reported: Severity | None = None
    source_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    country_code: str | None = None

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _no_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("Coordinates must be numbers.")
        return value

    @field_validator("location_name", "source_reference")
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        return _clean_text(value, allow_newlines=True)

    @field_validator("country_code")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return normalize_country(value)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return _clean_text(value, allow_newlines=True)


# Reports never carry usernames (per product decision). Identity is the internal user id only.
_SELECT = "SELECT r.* FROM reports r "


def content_sha256(row: sqlite3.Row) -> str:
    """Hash of what a reviewer reads. An offline decision must quote this value."""
    content = {key: row[key] for key in _CONTENT_FIELDS}
    return sha256_bytes(canonical_json(content).encode("utf-8"))


def _view(row: sqlite3.Row) -> dict[str, Any]:
    review = None
    if row["reviewed_by"] is not None:
        review = {"reviewer": {"id": row["reviewed_by"]}, "at": row["reviewed_at"], "note": row["review_note"]}
    return {
        "id": row["id"],
        "hazard_type": row["hazard_type"],
        "location": {"name": row["location_name"], "latitude": row["latitude"], "longitude": row["longitude"]},
        "observed_at": row["observed_at"],
        "reporter_role": row["reporter_role"],
        "severity_reported": row["severity_reported"],
        "source_reference": row["source_reference"],
        "notes": row["notes"],
        "status": row["status"],
        "country_code": country_or_default(row["country_code"]),
        "content_sha256": content_sha256(row),
        "submitter": {"id": row["submitter_id"]},
        "review": review,
        "created_at": row["created_at"],
    }


def _load(conn: sqlite3.Connection, report_id: str) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE r.id = ?", (report_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Report not found.")
    return row


def _visible(user: CurrentUser, status: str) -> bool:
    # Viewers read verified observations only (SDD 20.5). Analysts and above see every report.
    return status == "VERIFIED_OBSERVATION" or user.has_at_least("Analyst")


def visible_clause(user: CurrentUser) -> list[str]:
    """SQL form of _visible, for list queries and the sync snapshot."""
    return [] if user.has_at_least("Analyst") else ["r.status = 'VERIFIED_OBSERVATION'"]


def _observed_at(value: str | None) -> str | None:
    """Accept ISO 8601 with a timezone and store it as UTC `YYYY-MM-DDTHH:MM:SSZ`. Never guess a time zone."""
    if value is None:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AppError("VALIDATION_FAILED", "observed_at must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise AppError("VALIDATION_FAILED", "observed_at must include a time zone offset or Z.")
    utc = parsed.astimezone(UTC)
    if utc > datetime.now(UTC) + MAX_FUTURE_SKEW:
        raise AppError("VALIDATION_FAILED", "observed_at cannot be in the future.")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("")
def list_reports(request: Request, limit: int = Query(default=200, ge=1, le=500),
                 country: str | None = Query(default=None, max_length=2),
                 user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    clauses = visible_clause(user)
    params: list[str] = []
    frag, cparams = country_filter("r", country_query(country))
    if frag:
        clauses.append(frag)
        params += cparams
    where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
    with services_of(request).db.read() as conn:
        rows = conn.execute(_SELECT + where + "ORDER BY r.created_at DESC, r.id LIMIT ?",
                            (*params, limit)).fetchall()
    return [_view(r) for r in rows]


@router.post("", status_code=201)
def create_report(body: ReportIn, request: Request,
                  user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    services = services_of(request)
    with services.db.transaction() as conn:
        view = insert_report(conn, user, body)
    return JSONResponse(view, status_code=201)


def insert_report(conn: sqlite3.Connection, user: CurrentUser, body: ReportIn,
                  audit_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a report and its audit row inside an open transaction. Shared by the route and /api/sync/batch."""
    if (body.latitude is None) != (body.longitude is None):
        raise AppError("VALIDATION_FAILED", "Latitude and longitude must be given together, or both omitted.")
    observed_at = _observed_at(body.observed_at)
    report_id = new_id()
    conn.execute(
        "INSERT INTO reports (id, submitter_id, hazard_type, location_name, latitude, longitude, observed_at, "
        "reporter_role, severity_reported, source_reference, notes, status, created_at, country_code) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OBSERVATION', ?, ?)",
        (report_id, user.id, body.hazard_type, body.location_name, body.latitude, body.longitude, observed_at,
         body.reporter_role, body.severity_reported, body.source_reference, body.notes, utc_now(),
         body.country_code),
    )
    # The audit row stores hashes and flags, never the free text itself (SDD 16.4).
    audit.append(conn, actor=user.username, action="report.submitted", subject=report_id, detail={
        "hazard_type": body.hazard_type,
        "coordinates": body.latitude is not None,
        "named_place": body.location_name is not None,
        "notes_sha256": sha256_bytes(body.notes.encode("utf-8")) if body.notes else None,
        "country_code": country_or_default(body.country_code),
        **(audit_extra or {}),
    })
    return _view(_load(conn, report_id))


@router.get("/{report_id}")
def get_report(report_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        row = _load(conn, report_id)
    if not _visible(user, row["status"]):
        raise AppError("NOT_FOUND", "Report not found.")
    return _view(row)


@router.post("/{report_id}/review")
def review_report(report_id: str, body: ReviewBody, request: Request,
                  user: CurrentUser = Depends(require_role("Reviewer"))) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, report_id)
        if row["submitter_id"] == user.id:
            raise AppError("SELF_APPROVAL_NOT_ALLOWED", "You cannot review a report you submitted.")
        if row["status"] != "OBSERVATION":
            raise AppError("INVALID_STATE", f"A report in {row['status']} cannot be reviewed.")
        return apply_review(conn, user, row, body.decision, body.note)


def apply_review(conn: sqlite3.Connection, user: CurrentUser, row: sqlite3.Row, decision: str,
                 note: str | None, audit_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a review decision. The caller has already checked role, separation of duties, and state."""
    report_id = row["id"]
    target = "VERIFIED_OBSERVATION" if decision == "approve" else "REJECTED"
    conn.execute(
        "UPDATE reports SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
        (target, user.id, utc_now(), note, report_id),
    )
    audit.append(conn, actor=user.username, action="report.reviewed", subject=report_id, detail={
        "decision": decision, "role": user.role, "status": target,
        "note_sha256": sha256_bytes(note.encode("utf-8")) if note else None,
        **(audit_extra or {}),
    })
    alerts_core.write_report_verified(conn, row, target)
    return _view(_load(conn, report_id))
