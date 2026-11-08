"""What-if simulation runs on an approved flood CSV (SDD 14, docs/api.md section 2).

Analysts create runs. Viewers read them. A run is stored with its inputs, the verified dataset and rule-pack
hashes, and the SHA-256 of its output. Creating a run writes one audit row. Nothing else changes.
"""

from __future__ import annotations

import csv
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.errors import AppError
from app.routes.hazards import COLUMNS_MESSAGE, approved_csv_bytes
from app.rules import engine
from app.simulation import engine as sim
from app.util import new_id, sha256_bytes, utc_now

router = APIRouter(prefix="/simulations", tags=["simulations"])


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    pack: Literal["flood"] = "flood"
    depth_multiplier: float = Field(default=1.0, ge=sim.MIN_DEPTH_MULTIPLIER, le=sim.MAX_DEPTH_MULTIPLIER,
                                    allow_inf_nan=False)
    rise_cm_per_hour: float = Field(default=0.0, ge=0.0, le=sim.MAX_RISE_CM_PER_HOUR, allow_inf_nan=False)
    hours: int = Field(default=24, ge=1, le=sim.MAX_HOURS)


def _summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "dataset": {"id": row["dataset_id"], "name": row["dataset_name"]},
        "parameters": json.loads(row["parameters_json"]),
        "pack_sha256": row["pack_sha256"],
        "output_sha256": row["output_sha256"],
        "peak": {"hour": row["peak_hour"], "affected_rows": row["peak_affected_rows"]},
        "created_by": {"id": row["created_by"]},
        "created_at": row["created_at"],
    }


def _detail(row: Any) -> dict[str, Any]:
    return {
        **_summary(row),
        "dataset_sha256": row["dataset_sha256"],
        "pack": {"id": row["pack_id"], "sha256": row["pack_sha256"]},
        "simulator_version": row["simulator_version"],
        "output": json.loads(row["output_json"]),
    }


_SELECT = """
    SELECT s.*, d.name AS dataset_name
    FROM simulation_runs s JOIN datasets d ON d.id = s.dataset_id
"""


@router.get("")
def list_runs(request: Request, user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    with services_of(request).db.read() as conn:
        rows = conn.execute(_SELECT + " ORDER BY s.created_at DESC, s.id DESC LIMIT 100").fetchall()
    return [_summary(row) for row in rows]


@router.get("/{run_id}")
def get_run(run_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        row = conn.execute(_SELECT + " WHERE s.id = ?", (run_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Simulation run not found.")
    return _detail(row)


@router.post("", status_code=201)
def create_run(body: RunIn, request: Request,
               user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    name = body.name.strip()
    if not name:
        raise AppError("VALIDATION_FAILED", "Give the scenario a name.")
    services = services_of(request)
    with services.db.read() as conn:
        dataset, data = approved_csv_bytes(services.settings.data_dir, conn, body.dataset_id)
    try:
        records = engine.records_from_csv_bytes(data)
    except (ValueError, csv.Error):
        raise AppError("VALIDATION_FAILED", COLUMNS_MESSAGE) from None
    if all(item["water_depth_cm"] is None for item in records):
        raise AppError("VALIDATION_FAILED",
                       "This dataset has no water_depth_cm values to simulate from.")
    try:
        sim.check_budget(len(records), body.hours)
    except sim.ScenarioTooLarge as exc:
        raise AppError("VALIDATION_FAILED", str(exc)) from None

    _, pack = engine.load_default_pack()
    params = sim.Params(depth_multiplier=body.depth_multiplier, rise_cm_per_hour=body.rise_cm_per_hour,
                        hours=body.hours)
    output = sim.run_scenario(records, pack, params)
    output_bytes = engine.canonical_json(output)

    run_id = new_id()
    now = utc_now()
    with services.db.transaction() as conn:
        conn.execute(
            """INSERT INTO simulation_runs (id, name, dataset_id, dataset_sha256, pack_id, pack_sha256,
               simulator_version, parameters_json, output_json, output_sha256, peak_hour,
               peak_affected_rows, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, name, dataset["id"], dataset["sha256"], pack["pack_id"], pack[engine.PACK_HASH_FIELD],
             sim.SIMULATOR_VERSION, json.dumps(params.as_dict(), sort_keys=True),
             output_bytes.decode("ascii"), sha256_bytes(output_bytes), output["peak"]["hour"],
             output["peak"]["affected_rows"], user.id, now))
        audit.append(conn, actor=user.username, action="simulation.created", subject=run_id, detail={
            "dataset_id": dataset["id"], "pack_sha256": pack[engine.PACK_HASH_FIELD],
            "output_sha256": sha256_bytes(output_bytes), "parameters": params.as_dict()})
        row = conn.execute(_SELECT + " WHERE s.id = ?", (run_id,)).fetchone()
    return JSONResponse(_detail(row), status_code=201)
