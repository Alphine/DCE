"""Offline sync (docs/offline-global.md sections 2 and 4).

POST /api/sync/batch applies queued offline items. Each item runs in its own transaction, is recorded in sync_ops by
op_id, and is checked against the governance rules before anything is written. A replayed op_id returns DUPLICATE
with the stored result. Offline decisions must pass five checks at sync time: the user is still active with the
role, the item is still in the state it was decided against, the content hash matches, the decider is not the
proposer or submitter, and the decision is at most 72 hours old.

GET /api/sync/snapshot returns the list data a user may read, with an etag per section, for the PWA cache.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from app.auth import CurrentUser, require_role, session_user
from app.container import services_of
from app.countries import country_filter, country_query
from app.errors import AppError
from app.routes import datasets as datasets_api
from app.routes import missions as missions_api
from app.routes import reports as reports_api
from app.routes import simulations as simulations_api
from app.rules import engine
from app.util import canonical_json, sha256_bytes, utc_now

logger = logging.getLogger("dce.sync")

router = APIRouter(prefix="/sync", tags=["sync"])

MAX_ITEMS = 200
MAX_BODY_BYTES = 1_000_000
DECISION_WINDOW = timedelta(hours=72)
MAX_FUTURE_SKEW = timedelta(minutes=5)
SNAPSHOT_LIMIT = 1000
SNAPSHOT_SIMULATIONS = 100  # the same window as GET /api/simulations


class _Rejected(Exception):
    """A governance or validation failure. Raised before any write, so the item's savepoint rolls back."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _Ctx:
    op_id: str
    client_id: str
    made_at: datetime
    now: datetime

    def audit(self, made_key: str) -> dict[str, Any]:
        return {"offline": True, made_key: _iso(self.made_at), "synced_at": _iso(self.now),
                "op_id": self.op_id, "client_id": self.client_id}


class _ItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    op_id: str
    kind: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any]
    made_at: str = Field(min_length=1, max_length=40)


class _ReportDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(min_length=36, max_length=36)
    decision: Literal["approve", "reject"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return reports_api._clean_text(value, allow_newlines=True)


class _MissionDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=36, max_length=36)
    decision: Literal["approve", "reject"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return missions_api._required_text(value, "Note")


class _SimulationIn(simulations_api.RunIn):
    # The pack the device simulated against. The server runs only if its current pack has the same hash.
    pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _validate(model: type[BaseModel], data: Any) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        raise _Rejected("VALIDATION_FAILED", f"Invalid field: {loc}" if loc else "Invalid payload.") from None


def _parse_made_at(text: str) -> datetime:
    value = text.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _Rejected("VALIDATION_FAILED", "made_at must be an ISO 8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise _Rejected("VALIDATION_FAILED", "made_at must include a time zone offset or Z.")
    return parsed.astimezone(UTC)


def _fresh_user(conn: sqlite3.Connection, user: CurrentUser, min_role: str) -> CurrentUser:
    """Check 1 (section 2): the user still exists, is active, and has the role. Read at sync time, not at login."""
    row = conn.execute(
        "SELECT u.username, u.status, r.role FROM users u JOIN user_roles r ON r.user_id = u.id WHERE u.id = ?",
        (user.id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        raise _Rejected("USER_INACTIVE", "Your account is not active.")
    current = CurrentUser(id=user.id, username=row["username"], role=row["role"])
    if not current.has_at_least(min_role):
        raise _Rejected("FORBIDDEN", "Your role may not perform this action.")
    return current


def _check_window(ctx: _Ctx) -> None:
    """Check 5 (section 2): the decision was made no more than 72 hours before sync."""
    if ctx.made_at > ctx.now + MAX_FUTURE_SKEW:
        raise _Rejected("MADE_AT_IN_FUTURE", "The decision time is in the future. Check the device clock.")
    if ctx.now - ctx.made_at > DECISION_WINDOW:
        raise _Rejected("DECISION_EXPIRED", "This decision is more than 72 hours old. Decide again.")


def _report_create(conn: sqlite3.Connection, services: Any, user: CurrentUser, payload: dict[str, Any],
                   ctx: _Ctx) -> dict[str, Any]:
    current = _fresh_user(conn, user, "Analyst")
    body = _validate(reports_api.ReportIn, payload)
    view = reports_api.insert_report(conn, current, body, audit_extra=ctx.audit("made_offline_at"))
    return {"id": view["id"], "status": view["status"]}


def _report_decision(conn: sqlite3.Connection, services: Any, user: CurrentUser, payload: dict[str, Any],
                     ctx: _Ctx) -> dict[str, Any]:
    current = _fresh_user(conn, user, "Reviewer")                                   # check 1
    body = _validate(_ReportDecisionIn, payload)
    row = reports_api._load(conn, body.report_id)                                    # NOT_FOUND if missing
    if row["status"] != "OBSERVATION":                                               # check 2
        raise _Rejected("ITEM_STATE_CHANGED", f"This report is now {row['status']}.")
    if reports_api.content_sha256(row) != body.content_sha256:                       # check 3
        raise _Rejected("CONTENT_CHANGED", "The report changed after you decided. Review it again.")
    if row["submitter_id"] == current.id:                                            # check 4
        raise _Rejected("SELF_APPROVAL_NOT_ALLOWED", "You cannot review a report you submitted.")
    _check_window(ctx)                                                               # check 5
    view = reports_api.apply_review(conn, current, row, body.decision, body.note,
                                    audit_extra=ctx.audit("decided_offline_at"))
    return {"id": view["id"], "status": view["status"]}


def _mission_propose(conn: sqlite3.Connection, services: Any, user: CurrentUser, payload: dict[str, Any],
                     ctx: _Ctx) -> dict[str, Any]:
    current = _fresh_user(conn, user, "Analyst")
    body = _validate(missions_api.MissionIn, payload)
    view = missions_api.propose_in_conn(conn, services, current, body, audit_extra=ctx.audit("made_offline_at"))
    return {"id": view["id"], "status": view["status"]}


def _mission_decision(conn: sqlite3.Connection, services: Any, user: CurrentUser, payload: dict[str, Any],
                      ctx: _Ctx) -> dict[str, Any]:
    current = _fresh_user(conn, user, "Approver")                                    # check 1
    body = _validate(_MissionDecisionIn, payload)
    row = missions_api._load(conn, body.mission_id)                                  # NOT_FOUND if missing
    if row["status"] != "PROPOSED":                                                  # check 2
        raise _Rejected("ITEM_STATE_CHANGED", f"This mission is now {row['status']}.")
    current_sha = missions_api.mission_content_sha256(row)
    if current_sha != body.content_sha256 or current_sha != row["content_sha256"]:  # check 3
        raise _Rejected("CONTENT_CHANGED", "The mission changed after you decided. Review it again.")
    if row["proposer_id"] == current.id:                                             # check 4
        raise _Rejected("SELF_APPROVAL_NOT_ALLOWED", "You cannot approve a mission you proposed.")
    _check_window(ctx)                                                               # check 5
    view = missions_api.apply_decision(conn, current, row, body.decision, body.note, current_sha,
                                       audit_extra=ctx.audit("decided_offline_at"))
    return {"id": view["id"], "status": view["status"]}


def _simulation_create(conn: sqlite3.Connection, services: Any, user: CurrentUser, payload: dict[str, Any],
                       ctx: _Ctx) -> dict[str, Any]:
    current = _fresh_user(conn, user, "Analyst")
    body = _validate(_SimulationIn, payload)
    _, pack = engine.load_default_pack()
    if pack[engine.PACK_HASH_FIELD] != body.pack_sha256:
        raise _Rejected("PACK_MISMATCH", "The rule pack changed since this run was prepared.")
    detail = simulations_api.create_run_in_conn(conn, services, current, body,
                                                audit_extra=ctx.audit("made_offline_at"))
    return {"id": detail["id"], "output_sha256": detail["output_sha256"]}


_HANDLERS = {
    "REPORT_CREATE": _report_create,
    "REPORT_DECISION": _report_decision,
    "MISSION_PROPOSE": _mission_propose,
    "MISSION_DECISION": _mission_decision,
    "SIMULATION_CREATE": _simulation_create,
}


def _result(op_id: str | None, status: str, code: str, message: str, data: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"op_id": op_id, "status": status, "code": code, "message": message}
    if data is not None:
        result["data"] = data
    return result


def _apply(conn: sqlite3.Connection, services: Any, user: CurrentUser, client_id: str, raw: dict[str, Any],
           now: datetime) -> Any:
    item = _validate(_ItemIn, raw)
    made_at = _parse_made_at(item.made_at)
    handler = _HANDLERS.get(item.kind)
    if handler is None:
        raise _Rejected("UNKNOWN_KIND", "Unknown item kind.")
    ctx = _Ctx(op_id=item.op_id, client_id=client_id, made_at=made_at, now=now)
    return handler(conn, services, user, item.payload, ctx)


def _process_item(services: Any, user: CurrentUser, client_id: str, raw: Any) -> dict[str, Any]:
    op_id = raw.get("op_id") if isinstance(raw, dict) else None
    if not _is_uuid(op_id):
        return _result(None, "REJECTED", "VALIDATION_FAILED", "Each item needs a UUID op_id.")
    now = datetime.now(UTC)
    with services.db.transaction() as conn:
        stored = conn.execute("SELECT user_id, result_json FROM sync_ops WHERE op_id = ?", (op_id,)).fetchone()
        if stored is not None:
            if stored["user_id"] != user.id:
                return _result(op_id, "REJECTED", "OP_ID_IN_USE", "This op_id belongs to another account.")
            return {**_result(op_id, "DUPLICATE", "DUPLICATE", "Already processed. No change made."),
                    "result": json.loads(stored["result_json"])}
        kind = raw.get("kind") if isinstance(raw.get("kind"), str) else ""
        conn.execute("SAVEPOINT item")
        try:
            data = _apply(conn, services, user, client_id, raw, now)
            conn.execute("RELEASE item")
            result = _result(op_id, "APPLIED", "APPLIED", "Applied.", data)
        except (_Rejected, AppError) as exc:
            conn.execute("ROLLBACK TO item")
            conn.execute("RELEASE item")
            result = _result(op_id, "REJECTED", exc.code, exc.message)
        except Exception:
            logger.exception("sync item failed op_id=%s kind=%s", op_id, kind)
            conn.execute("ROLLBACK TO item")
            conn.execute("RELEASE item")
            result = _result(op_id, "REJECTED", "INTERNAL", "Internal error.")
        conn.execute(
            "INSERT INTO sync_ops (op_id, user_id, kind, status, created_at, result_json) VALUES (?, ?, ?, ?, ?, ?)",
            (op_id, user.id, kind, result["status"], utc_now(), canonical_json(result)),
        )
    return result


def _run_items(services: Any, user: CurrentUser, client_id: str, items: list[Any]) -> list[dict[str, Any]]:
    return [_process_item(services, user, client_id, raw) for raw in items]


async def _read_capped(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise AppError("VALIDATION_FAILED", "The batch is larger than 1 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/batch")
async def sync_batch(request: Request, user: CurrentUser = Depends(session_user)) -> dict[str, Any]:
    """Session cookie only: API keys are refused. Any signed-in role may send a batch, and each item is checked
    against that role. Limits: 200 items and 1 MB (422 when over)."""
    raw = await _read_capped(request)
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        raise AppError("VALIDATION_FAILED", "The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise AppError("VALIDATION_FAILED", "The request body must be a JSON object.")
    client_id = body.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 64:
        raise AppError("VALIDATION_FAILED", "client_id is required (up to 64 characters).")
    items = body.get("items")
    if not isinstance(items, list):
        raise AppError("VALIDATION_FAILED", "items must be a list.")
    if len(items) > MAX_ITEMS:
        raise AppError("VALIDATION_FAILED", f"A batch holds at most {MAX_ITEMS} items.")
    services = services_of(request)
    results = await run_in_threadpool(_run_items, services, user, client_id.strip(), items)
    return {"results": results, "synced_at": utc_now()}


def _where(clauses: list[str]) -> str:
    return ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""


def _section(items: list[dict[str, Any]], truncated: bool) -> dict[str, Any]:
    return {"etag": sha256_bytes(canonical_json(items).encode("utf-8")), "count": len(items),
            "truncated": truncated, "items": items}


def _fetch(conn: sqlite3.Connection, base: str, clauses: list[str], params: list[str], order: str,
           limit: int, mapper: Any) -> dict[str, Any]:
    """Run one section query. Fetches one extra row to learn whether the section was truncated."""
    rows = conn.execute(base + _where(clauses) + order, (*params, limit + 1)).fetchall()
    items = [mapper(r) for r in rows[:limit]]
    return _section(items, truncated=len(rows) > limit)


@router.get("/snapshot")
def sync_snapshot(request: Request, country: str | None = Query(default=None, max_length=2),
                  user: CurrentUser = Depends(require_role("Viewer"))) -> dict[str, Any]:
    """The list data the PWA caches. Each section uses the same visibility as its list endpoint for this user."""
    code = country_query(country)
    frag_r, params_r = country_filter("r", code)
    frag_d, params_d = country_filter("d", code)
    frag_m, params_m = country_filter("m", code)
    frag_s, params_s = country_filter("s", code)
    with services_of(request).db.read() as conn:
        reports = _fetch(conn, reports_api._SELECT, reports_api.visible_clause(user) + _opt(frag_r),
                         params_r, "ORDER BY r.created_at DESC, r.id LIMIT ?", SNAPSHOT_LIMIT, reports_api._view)
        dataset_clauses = [] if user.has_at_least("Analyst") else ["d.status = 'APPROVED'"]
        datasets = _fetch(conn, datasets_api._SELECT, dataset_clauses + _opt(frag_d), params_d,
                          "ORDER BY d.created_at DESC LIMIT ?", SNAPSHOT_LIMIT, datasets_api._dataset_view)
        missions = _fetch(conn, missions_api._SELECT, missions_api.visible_clause(user) + _opt(frag_m), params_m,
                          "ORDER BY m.created_at DESC, m.id LIMIT ?", SNAPSHOT_LIMIT, missions_api._view)
        simulations = _fetch(conn, simulations_api._SELECT, _opt(frag_s), params_s,
                             "ORDER BY s.created_at DESC, s.id DESC LIMIT ?", SNAPSHOT_SIMULATIONS,
                             simulations_api._summary)
    return {
        "country": code,
        "generated_at": utc_now(),
        "sections": {"reports": reports, "datasets": datasets, "missions": missions, "simulations": simulations},
    }


def _opt(fragment: str) -> list[str]:
    return [fragment] if fragment else []
