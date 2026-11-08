"""Wildfire distance-to-settlement bands and smoke-exposure candidate flag (illustrative, SDD 11.3).

Input CSV: `distance_km` (required, distance from the nearest settlement) and `wind_kmh` (optional).
Optional: `district` / `district_name` / `location`. Loader and evaluator are shared with app/rules/generic.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rules.generic import PackSpec, evaluate_generic, parse_generic_pack, records_from_csv

DEFAULT_WILDFIRE_PACK_PATH = Path(__file__).with_name("wildfire_v1.json")
HAZARD_NAME = "wildfire"
SPEC = PackSpec(
    hazard=HAZARD_NAME,
    tool="wildfire_analyzer",
    required=("distance_km",),
    numeric=("distance_km", "wind_kmh"),
    boolean=(),
    flags=frozenset({"smoke_exposure_candidate"}),
)


def parse_wildfire_pack(data: bytes) -> dict[str, Any]:
    return parse_generic_pack(data, SPEC)


def load_default_wildfire_pack() -> tuple[bytes, dict[str, Any]]:
    data = DEFAULT_WILDFIRE_PACK_PATH.read_bytes()
    return data, parse_wildfire_pack(data)


def records_from_csv_bytes(data: bytes) -> list[dict[str, Any]]:
    return records_from_csv(data, SPEC)


def evaluate_wildfire(records: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    return evaluate_generic(records, pack, SPEC)
