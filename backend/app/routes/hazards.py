"""Hazard rule results for an approved CSV dataset (docs/api.md section 2).

Read-only. The rules come from verified, hash-checked packs (app/rules). The model never supplies or changes them.
Viewers may read results for approved datasets. Nothing here writes to the audit log.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.auth import CurrentUser, current_user
from app.container import services_of
from app.datasets import KIND_CSV, dataset_file
from app.errors import AppError
from app.rules import earthquake, engine, tsunami, wildfire
from app.util import sha256_bytes

router = APIRouter(prefix="/hazards", tags=["hazards"])

Pack = Literal["flood", "tsunami", "earthquake", "wildfire"]
COLUMNS_MESSAGE = "This dataset does not have the columns this rule pack needs."


def approved_csv_bytes(data_dir: Path, conn: sqlite3.Connection, dataset_id: str) -> tuple[sqlite3.Row, bytes]:
    """Return the dataset row and its verified bytes. Not-approved datasets look missing (SDD: do not reveal)."""
    row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if row is None or row["status"] != "APPROVED":
        raise AppError("NOT_FOUND", "Dataset not found.")
    if row["kind"] != KIND_CSV:
        raise AppError("VALIDATION_FAILED", "Hazard rules apply to CSV datasets only.")
    path = dataset_file(data_dir, row["storage_name"])
    if not path.is_file():
        raise AppError("NOT_FOUND", "Dataset file is missing.")
    data = path.read_bytes()
    if sha256_bytes(data) != row["sha256"]:
        raise AppError("CONFLICT", "Dataset file failed its integrity check.")
    return row, data


def evaluate_pack(data: bytes, pack: str) -> dict[str, Any]:
    """Run the named pack. A dataset missing the columns a pack needs is refused, never a server error."""
    try:
        if pack == "flood":
            loaded = engine.load_default_pack()[1]
            result = engine.evaluate_hazards(engine.records_from_csv_bytes(data), loaded)
        elif pack == "tsunami":
            loaded = tsunami.load_default_tsunami_pack()[1]
            result = tsunami.evaluate_tsunami(tsunami.records_from_csv_bytes(data), loaded)
        elif pack == "earthquake":
            loaded = earthquake.load_default_earthquake_pack()[1]
            result = earthquake.evaluate_earthquake(earthquake.records_from_csv_bytes(data), loaded)
        else:
            loaded = wildfire.load_default_wildfire_pack()[1]
            result = wildfire.evaluate_wildfire(wildfire.records_from_csv_bytes(data), loaded)
    except (ValueError, KeyError, csv.Error):
        raise AppError("VALIDATION_FAILED", COLUMNS_MESSAGE) from None
    # Every pack exposes its declared countries. A pack without the field means any country.
    result["rule_pack"].setdefault("countries", list(loaded.get("countries", [])))
    return result


@router.get("")
def hazard_results(request: Request, dataset_id: str = Query(),
                   pack: Pack = Query(default="flood"),
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    services = services_of(request)
    with services.db.read() as conn:
        row, data = approved_csv_bytes(services.settings.data_dir, conn, dataset_id)
    result = evaluate_pack(data, pack)
    return {**result, "dataset": {"id": row["id"], "name": row["name"]}}
