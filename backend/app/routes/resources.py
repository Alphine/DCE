"""Illustrative resource estimate for an approved flood CSV (docs/api.md section 2).

Output is SIMULATED_FACT from illustrative ratios in the verified flood pack. Not for operational use.
An estimate writes no audit row. Only Analysts and above may request one.
"""

from __future__ import annotations

import csv
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import CurrentUser, require_role
from app.container import services_of
from app.errors import AppError
from app.routes.hazards import COLUMNS_MESSAGE, approved_csv_bytes
from app.rules import engine

router = APIRouter(prefix="/resources", tags=["resources"])


class EstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=36, max_length=36)
    pack: Literal["flood"]


@router.post("/estimate")
def estimate_resources(body: EstimateIn, request: Request,
                       user: CurrentUser = Depends(require_role("Analyst"))) -> dict[str, Any]:
    services = services_of(request)
    with services.db.read() as conn:
        row, data = approved_csv_bytes(services.settings.data_dir, conn, body.dataset_id)
    try:
        records = engine.records_from_csv_bytes(data)
    except (ValueError, csv.Error):
        raise AppError("VALIDATION_FAILED", COLUMNS_MESSAGE) from None
    if all(item["water_depth_cm"] is None for item in records):
        raise AppError("VALIDATION_FAILED",
                       "This dataset has no water_depth_cm values to estimate resources from.")
    result = engine.estimate_resources(records, engine.load_default_pack()[1])
    return {**result, "dataset": {"id": row["id"], "name": row["name"]}}
