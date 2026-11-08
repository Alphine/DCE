"""Earthquake magnitude severity bands and tsunami-check candidate flag (illustrative, SDD 11.3).

Input CSV: `magnitude` (required). Optional: `district` / `district_name` / `location`, and `coastal` (true/false).
Loader and evaluator are shared with the other packs in app/rules/generic.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rules.generic import PackSpec, evaluate_generic, parse_generic_pack, records_from_csv

DEFAULT_EARTHQUAKE_PACK_PATH = Path(__file__).with_name("earthquake_v1.json")
HAZARD_NAME = "earthquake"
SPEC = PackSpec(
    hazard=HAZARD_NAME,
    tool="earthquake_analyzer",
    required=("magnitude",),
    numeric=("magnitude",),
    boolean=("coastal",),
    flags=frozenset({"tsunami_check_candidate"}),
)


def parse_earthquake_pack(data: bytes) -> dict[str, Any]:
    return parse_generic_pack(data, SPEC)


def load_default_earthquake_pack() -> tuple[bytes, dict[str, Any]]:
    data = DEFAULT_EARTHQUAKE_PACK_PATH.read_bytes()
    return data, parse_earthquake_pack(data)


def records_from_csv_bytes(data: bytes) -> list[dict[str, Any]]:
    return records_from_csv(data, SPEC)


def evaluate_earthquake(records: list[dict[str, Any]], pack: dict[str, Any]) -> dict[str, Any]:
    return evaluate_generic(records, pack, SPEC)
