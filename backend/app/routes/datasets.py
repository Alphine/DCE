"""Dataset routes: CSV upload, listing, detail, and approval (docs/api.md section 3)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.datasets import (MAX_UPLOAD_BYTES, clean_name, dataset_file, parse_csv_bytes, read_table,
                          typed_row, validate_filename, write_dataset_file)
from app.errors import AppError
from app.util import new_id, sha256_bytes, utc_now

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _dataset_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "status": row["status"],
        "owner": {"id": row["owner_id"], "username": row["owner_username"]},
        "profile": json.loads(row["profile_json"]),
        "created_at": row["created_at"],
    }


_SELECT = ("SELECT d.*, u.username AS owner_username FROM datasets d JOIN users u ON u.id = d.owner_id ")


def _load(conn: sqlite3.Connection, dataset_id: str) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE d.id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Dataset not found.")
    return row


def _visible(user: CurrentUser, status: str) -> bool:
    # Viewers see approved datasets only. Analysts and above see every dataset (SDD 20.4).
    return status == "APPROVED" or user.has_at_least("Analyst")


@router.get("")
def list_datasets(request: Request, user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    with services_of(request).db.read() as conn:
        rows = conn.execute(_SELECT + "ORDER BY d.created_at DESC").fetchall()
    return [_dataset_view(r) for r in rows if _visible(user, r["status"])]


@router.post("", status_code=201)
def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    user: CurrentUser = Depends(require_role("Analyst")),
) -> JSONResponse:
    services = services_of(request)
    filename = validate_filename(file.filename)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    display_name = clean_name(name, filename)
    parsed = parse_csv_bytes(data)

    dataset_id = new_id()
    storage_name = f"{dataset_id}.csv"
    write_dataset_file(services.settings.data_dir, storage_name, data)
    try:
        with services.db.transaction() as conn:
            conn.execute(
                "INSERT INTO datasets (id, name, filename, size_bytes, sha256, status, owner_id, storage_name, "
                "profile_json, created_at) VALUES (?, ?, ?, ?, ?, 'PENDING_VALIDATION', ?, ?, ?, ?)",
                (dataset_id, display_name, filename, parsed.size_bytes, parsed.sha256, user.id, storage_name,
                 _json(parsed.profile), utc_now()),
            )
            audit.append(conn, actor=user.username, action="dataset.uploaded", subject=dataset_id, detail={
                "sha256": parsed.sha256, "size_bytes": parsed.size_bytes, "rows": parsed.profile["rows"],
            })
            row = _load(conn, dataset_id)
            view = _dataset_view(row)
    except BaseException:
        dataset_file(services.settings.data_dir, storage_name).unlink(missing_ok=True)
        raise
    return JSONResponse(view, status_code=201)


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        row = _load(conn, dataset_id)
    if not _visible(user, row["status"]):
        raise AppError("NOT_FOUND", "Dataset not found.")
    return _dataset_view(row)


@router.get("/{dataset_id}/rows")
def dataset_rows(dataset_id: str, request: Request,
                 limit: int = Query(default=500, ge=1, le=1000), offset: int = Query(default=0, ge=0),
                 user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    services = services_of(request)
    with services.db.read() as conn:
        row = _load(conn, dataset_id)
    if row["status"] != "APPROVED" and row["owner_id"] != user.id:
        raise AppError("NOT_FOUND", "Dataset not found.")
    path = dataset_file(services.settings.data_dir, row["storage_name"])
    if not path.is_file():
        raise AppError("NOT_FOUND", "Dataset file is missing.")
    data = path.read_bytes()
    if sha256_bytes(data) != row["sha256"]:
        raise AppError("CONFLICT", "Dataset file failed its integrity check.")
    columns, rows = read_table(data)
    items = [typed_row(columns, r) for r in rows[offset: offset + limit]]
    next_offset = offset + limit if offset + limit < len(rows) else None
    return {"items": items, "next_offset": next_offset, "total": len(rows)}


@router.post("/{dataset_id}/approve")
def approve_dataset(dataset_id: str, request: Request,
                    user: CurrentUser = Depends(require_role("Reviewer"))) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        row = _load(conn, dataset_id)
        if row["owner_id"] == user.id:
            raise AppError("SELF_APPROVAL_NOT_ALLOWED", "You cannot approve a dataset you uploaded.")
        if row["status"] != "PENDING_VALIDATION":
            raise AppError("INVALID_STATE", f"A dataset in {row['status']} cannot be approved.")
        now = utc_now()
        conn.execute("UPDATE datasets SET status = 'APPROVED', approved_by = ?, approved_at = ? WHERE id = ?",
                     (user.id, now, dataset_id))
        audit.append(conn, actor=user.username, action="dataset.approved", subject=dataset_id,
                     detail={"sha256": row["sha256"]})
        row = _load(conn, dataset_id)
        view = _dataset_view(row)
    return view


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
