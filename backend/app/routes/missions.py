"""Mission proposal and human approval (SDD 15.2 to 15.4): docs/api.md section 2.

A mission is proposed by an Analyst from an approved CSV dataset or a verified report. Target areas are read
from the data, never typed in. An Approver who did not propose the mission decides it. Nothing here starts a
sandbox run or changes an agent task.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.datasets import KIND_CSV, dataset_file, read_table
from app.errors import AppError
from app.util import canonical_json, new_id, sha256_bytes, utc_now

router = APIRouter(prefix="/missions", tags=["missions"])

MAX_TARGET_AREAS = 50
MAX_AREA_CHARS = 120


def _required_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    for ch in text:
        if ord(ch) < 32 and ch not in "\n\t":
            raise ValueError(f"{label} cannot contain control characters.")
    return text


class MissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["DATASET", "REPORT"]
    source_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1000)
    # Required for DATASET sources: the CSV column whose distinct values become the target areas.
    area_column: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _required_text(value, "Title")

    @field_validator("objective")
    @classmethod
    def _objective(cls, value: str) -> str:
        return _required_text(value, "Objective")

    @field_validator("area_column")
    @classmethod
    def _column(cls, value: str | None) -> str | None:
        return None if value is None else _required_text(value, "Area column")


class DecisionBody(BaseModel):
    """Optional note for POST /approve and POST /reject. The decision is in the path, not the body."""

    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _required_text(value, "Note")


_SELECT = ("SELECT m.*, p.username AS proposer_username, d.username AS decider_username "
           "FROM missions m JOIN users p ON p.id = m.proposer_id LEFT JOIN users d ON d.id = m.decided_by ")


def _content(title: str, objective: str, source_type: str, source_id: str, target_areas: list[str]) -> str:
    return canonical_json({"title": title, "objective": objective, "source_type": source_type,
                           "source_id": source_id, "target_areas": target_areas})


def _view(row: sqlite3.Row) -> dict[str, Any]:
    source_id = row["dataset_id"] if row["source_type"] == "DATASET" else row["report_id"]
    decision = None
    if row["decided_by"] is not None:
        decision = {"decided_by": {"id": row["decided_by"], "username": row["decider_username"]},
                    "role": row["decided_role"], "at": row["decided_at"], "note": row["decision_note"]}
    return {
        "id": row["id"],
        "title": row["title"],
        "objective": row["objective"],
        "source": {"type": row["source_type"], "id": source_id},
        "area_column": row["area_column"],
        "target_areas": json.loads(row["target_areas_json"]),
        "status": row["status"],
        "content_sha256": row["content_sha256"],
        "approved_content_sha256": row["approved_content_sha256"],
        "proposer": {"id": row["proposer_id"], "username": row["proposer_username"]},
        "decision": decision,
        "created_at": row["created_at"],
    }


def _load(conn: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE m.id = ?", (mission_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Mission not found.")
    return row


def _visible(user: CurrentUser, status: str) -> bool:
    # Viewers read approved missions only. Analysts and above see every mission.
    return status == "APPROVED" or user.has_at_least("Analyst")


def _areas_from_dataset(data_dir: Path, dataset: sqlite3.Row, column: str) -> list[str]:
    path = dataset_file(data_dir, dataset["storage_name"])
    if not path.is_file():
        raise AppError("NOT_FOUND", "Dataset file is missing.")
    data = path.read_bytes()
    if sha256_bytes(data) != dataset["sha256"]:
        raise AppError("CONFLICT", "Dataset file failed its integrity check.")
    columns, rows = read_table(data)
    if column not in columns:
        raise AppError("VALIDATION_FAILED", "Unknown area column for this dataset.")
    idx = columns.index(column)
    areas = sorted({r[idx].strip() for r in rows if r[idx].strip()})
    if not areas:
        raise AppError("VALIDATION_FAILED", "The area column has no values.")
    if len(areas) > MAX_TARGET_AREAS:
        raise AppError("VALIDATION_FAILED", f"The area column has more than {MAX_TARGET_AREAS} distinct values.")
    if any(len(a) > MAX_AREA_CHARS for a in areas):
        raise AppError("VALIDATION_FAILED", "An area value is too long.")
    return areas


@router.get("")
def list_missions(request: Request, limit: int = Query(default=200, ge=1, le=500),
                  user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    where = "" if user.has_at_least("Analyst") else "WHERE m.status = 'APPROVED' "
    with services_of(request).db.read() as conn:
        rows = conn.execute(_SELECT + where + "ORDER BY m.created_at DESC, m.id LIMIT ?", (limit,)).fetchall()
    return [_view(r) for r in rows]


@router.post("", status_code=201)
def propose_mission(body: MissionIn, request: Request,
                    user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    services = services_of(request)
    with services.db.transaction() as conn:
        if body.source_type == "DATASET":
            dataset = conn.execute("SELECT * FROM datasets WHERE id = ?", (body.source_id,)).fetchone()
            if dataset is None:
                raise AppError("NOT_FOUND", "Dataset not found.")
            if dataset["status"] != "APPROVED":
                raise AppError("INVALID_STATE", "A mission can only use an approved dataset.")
            if dataset["kind"] != KIND_CSV:
                raise AppError("VALIDATION_FAILED", "Target areas are derived from CSV datasets only.")
            if body.area_column is None:
                raise AppError("VALIDATION_FAILED", "area_column is required for a dataset source.")
            target_areas = _areas_from_dataset(services.settings.data_dir, dataset, body.area_column)
            dataset_id, report_id = dataset["id"], None
        else:
            if body.area_column is not None:
                raise AppError("VALIDATION_FAILED", "area_column applies to dataset sources only.")
            report = conn.execute("SELECT * FROM reports WHERE id = ?", (body.source_id,)).fetchone()
            if report is None:
                raise AppError("NOT_FOUND", "Report not found.")
            if report["status"] != "VERIFIED_OBSERVATION":
                raise AppError("INVALID_STATE", "A mission can only use a verified report.")
            if report["location_name"] is None:
                raise AppError("VALIDATION_FAILED", "The report has no named place to use as a target area.")
            target_areas = [report["location_name"]]
            dataset_id, report_id = None, report["id"]

        content_sha = sha256_bytes(
            _content(body.title, body.objective, body.source_type, body.source_id, target_areas).encode("utf-8"))
        mission_id = new_id()
        conn.execute(
            "INSERT INTO missions (id, title, objective, source_type, dataset_id, report_id, area_column, "
            "target_areas_json, content_sha256, status, proposer_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)",
            (mission_id, body.title, body.objective, body.source_type, dataset_id, report_id,
             body.area_column, canonical_json(target_areas), content_sha, user.id, utc_now()),
        )
        audit.append(conn, actor=user.username, action="mission.proposed", subject=mission_id, detail={
            "source_type": body.source_type, "source_id": body.source_id,
            "target_area_count": len(target_areas), "content_sha256": content_sha,
        })
        view = _view(_load(conn, mission_id))
    return JSONResponse(view, status_code=201)


@router.get("/{mission_id}")
def get_mission(mission_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        row = _load(conn, mission_id)
    if not _visible(user, row["status"]):
        raise AppError("NOT_FOUND", "Mission not found.")
    return _view(row)


def _decide(request: Request, user: CurrentUser, mission_id: str, decision: str, note: str | None) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, mission_id)
        if row["proposer_id"] == user.id:
            raise AppError("SELF_APPROVAL_NOT_ALLOWED", "You cannot approve a mission you proposed.")
        if row["status"] != "PROPOSED":
            raise AppError("INVALID_STATE", f"A mission in {row['status']} cannot be decided.")
        target_areas = json.loads(row["target_areas_json"])
        source_id = row["dataset_id"] if row["source_type"] == "DATASET" else row["report_id"]
        content_sha = sha256_bytes(_content(row["title"], row["objective"], row["source_type"], source_id,
                                            target_areas).encode("utf-8"))
        if content_sha != row["content_sha256"]:
            raise AppError("CONFLICT", "Mission content no longer matches its proposal hash.")
        now = utc_now()
        if decision == "approve":
            conn.execute(
                "UPDATE missions SET status = 'APPROVED', decided_by = ?, decided_role = ?, decided_at = ?, "
                "decision_note = ?, approved_content_sha256 = ? WHERE id = ?",
                (user.id, user.role, now, note, content_sha, mission_id),
            )
            action = "mission.approved"
        else:
            conn.execute(
                "UPDATE missions SET status = 'REJECTED', decided_by = ?, decided_role = ?, decided_at = ?, "
                "decision_note = ? WHERE id = ?",
                (user.id, user.role, now, note, mission_id),
            )
            action = "mission.rejected"
        audit.append(conn, actor=user.username, action=action, subject=mission_id, detail={
            "role": user.role, "content_sha256": content_sha,
            "note_sha256": sha256_bytes(note.encode("utf-8")) if note else None,
        })
        view = _view(_load(conn, mission_id))
    return view


@router.post("/{mission_id}/approve")
def approve_mission(mission_id: str, request: Request, body: DecisionBody | None = None,
                    user: CurrentUser = Depends(require_role("Approver"))) -> dict[str, Any]:
    """SDD 18.1 and 15.4: Approver (not the requester). Admin also passes via require_role, as for gate A."""
    return _decide(request, user, mission_id, "approve", body.note if body else None)


@router.post("/{mission_id}/reject")
def reject_mission(mission_id: str, request: Request, body: DecisionBody | None = None,
                   user: CurrentUser = Depends(require_role("Approver"))) -> dict[str, Any]:
    """Not in SDD 18.1. Kept so a proposal can be closed without approval. Same rules as approve."""
    return _decide(request, user, mission_id, "reject", body.note if body else None)
