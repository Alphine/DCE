"""Situation picture for the map (docs/api.md section 2).

Two sources only: VERIFIED_OBSERVATION reports that have coordinates, and approved CSV datasets with lat and lon
columns. A place name never becomes a coordinate. A row without valid coordinates is skipped. A dataset whose file
is missing or fails its integrity check is skipped silently, so one bad file does not fail the whole request.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.auth import CurrentUser, current_user
from app.container import services_of
from app.datasets import KIND_CSV, dataset_file, read_table
from app.errors import AppError
from app.util import sha256_bytes

router = APIRouter(prefix="/situation", tags=["situation"])

LABEL_CHARS = 120


def _report_points(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, hazard_type, location_name, latitude, longitude, status FROM reports "
        "WHERE status = 'VERIFIED_OBSERVATION' AND latitude IS NOT NULL AND longitude IS NOT NULL "
        "ORDER BY created_at DESC, id LIMIT ?",
        (limit,),
    ).fetchall()
    return [{
        "kind": "REPORT",
        "id": row["id"],
        "label": f"{row['hazard_type']} · {row['location_name'] or 'unnamed place'}",
        "lat": row["latitude"],
        "lon": row["longitude"],
        "status": row["status"],
        "data_class": "VERIFIED_OBSERVATION",
    } for row in rows]


def _as_number(text: str) -> float | None:
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _as_coordinate(text: str, low: float, high: float) -> float | None:
    value = _as_number(text)
    if value is None or not low <= value <= high:
        return None
    return value


def _coordinate_columns(columns: list[str]) -> tuple[int, int] | None:
    lowered: dict[str, int] = {}
    for idx, name in enumerate(columns):
        lowered.setdefault(name.strip().lower(), idx)
    if "lat" not in lowered or "lon" not in lowered:
        return None
    return lowered["lat"], lowered["lon"]


def _dataset_points(data: bytes, dataset: sqlite3.Row, budget: int) -> list[dict[str, Any]]:
    columns, rows = read_table(data)  # raises AppError on a malformed file; the caller skips the dataset
    indexes = _coordinate_columns(columns)
    if indexes is None:
        return []
    lat_idx, lon_idx = indexes
    points: list[dict[str, Any]] = []
    for number, row in enumerate(rows, start=1):
        if len(points) >= budget:
            break
        lat = _as_coordinate(row[lat_idx], -90, 90)
        lon = _as_coordinate(row[lon_idx], -180, 180)
        if lat is None or lon is None:
            continue
        text_cells = [cell.strip() for cell in row if cell.strip() and _as_number(cell) is None]
        points.append({
            "kind": "DATASET_ROW",
            "dataset_id": dataset["id"],
            "dataset_name": dataset["name"],
            "row": number,
            "label": text_cells[0][:LABEL_CHARS] if text_cells else dataset["name"],
            "lat": lat,
            "lon": lon,
            "data_class": None,
        })
    return points


def _dataset_rows(conn: sqlite3.Connection, data_dir: Path, budget: int) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    datasets = conn.execute(
        "SELECT * FROM datasets WHERE status = 'APPROVED' AND kind = ? ORDER BY created_at, id", (KIND_CSV,),
    ).fetchall()
    for dataset in datasets:
        if len(points) >= budget:
            break
        path = dataset_file(data_dir, dataset["storage_name"])
        if not path.is_file():
            continue
        data = path.read_bytes()
        if sha256_bytes(data) != dataset["sha256"]:
            continue
        try:
            points.extend(_dataset_points(data, dataset, budget - len(points)))
        except AppError:
            continue
    return points


@router.get("")
def situation(request: Request, limit: int = Query(default=500, ge=1, le=2000),
              user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    services = services_of(request)
    wanted = limit + 1  # one extra point tells us that something was cut
    with services.db.read() as conn:
        points = _report_points(conn, wanted)
        if len(points) < wanted:
            points.extend(_dataset_rows(conn, services.settings.data_dir, wanted - len(points)))
    truncated = len(points) > limit
    points = points[:limit]
    counts = {"REPORT": 0, "DATASET_ROW": 0}
    for point in points:
        counts[point["kind"]] += 1
    return {"points": points, "counts": counts, "truncated": truncated}
