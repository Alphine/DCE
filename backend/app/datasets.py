"""CSV dataset validation, profiling (standard library only), and storage (docs/api.md section 3)."""

from __future__ import annotations

import csv
import io
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.errors import AppError
from app.util import sha256_bytes

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_COLUMNS = 200
PREVIEW_ROWS = 5
_BOOL_VALUES = {"true", "false", "yes", "no"}
_INT_RE = re.compile(r"^[+-]?\d+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9 _().-]{1,120}$")
_STORAGE_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.csv$")


@dataclass(frozen=True)
class ParsedDataset:
    size_bytes: int
    sha256: str
    profile: dict[str, Any]


def validate_filename(filename: str | None) -> str:
    base = os.path.basename(filename or "")
    if not base or not base.lower().endswith(".csv") or len(base) > 200:
        raise AppError("VALIDATION_FAILED", "Only .csv files are accepted.")
    if any(ord(ch) < 32 for ch in base):
        raise AppError("VALIDATION_FAILED", "Invalid file name.")
    return base


def clean_name(name: str | None, filename: str) -> str:
    candidate = (name or "").strip() or Path(filename).stem
    if not _NAME_RE.match(candidate):
        raise AppError("VALIDATION_FAILED", "Dataset name may use letters, digits, spaces and ( ) . _ -.")
    return candidate


def _is_null(value: str) -> bool:
    return value.strip() == ""


def _float_ok(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except ValueError:
        return False


def _typed(value: str) -> Any:
    if _is_null(value):
        return None
    stripped = value.strip()
    if _INT_RE.match(stripped):
        return int(stripped)
    if _float_ok(stripped):
        return float(stripped)
    if stripped.lower() in _BOOL_VALUES:
        return stripped.lower() in ("true", "yes")
    return value


def _infer_dtype(values: list[str]) -> str:
    present = [v.strip() for v in values if not _is_null(v)]
    if not present:
        return "string"
    if all(_INT_RE.match(v) for v in present):
        return "integer"
    if all(_float_ok(v) for v in present):
        return "float"
    if all(v.lower() in _BOOL_VALUES for v in present):
        return "boolean"
    return "string"


def read_table(data: bytes) -> tuple[list[str], list[list[str]]]:
    """Validate CSV bytes and return (columns, rows). Raises AppError(VALIDATION_FAILED) on any problem."""
    if len(data) == 0:
        raise AppError("VALIDATION_FAILED", "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("VALIDATION_FAILED", "File exceeds the 10 MB limit.", status=413)
    if b"\x00" in data:
        raise AppError("VALIDATION_FAILED", "Binary content is not accepted.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("VALIDATION_FAILED", "The file must be UTF-8 encoded.") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise AppError("VALIDATION_FAILED", "The file has no header row.") from exc
    columns = [c.strip() for c in header]
    if not columns or all(c == "" for c in columns):
        raise AppError("VALIDATION_FAILED", "The header row is empty.")
    if any(c == "" for c in columns):
        raise AppError("VALIDATION_FAILED", "Every column needs a name in the header row.")
    if len(set(columns)) != len(columns):
        raise AppError("VALIDATION_FAILED", "Column names in the header must be unique.")
    if len(columns) > MAX_COLUMNS:
        raise AppError("VALIDATION_FAILED", "Too many columns.")

    rows: list[list[str]] = []
    for line_no, row in enumerate(reader, start=2):
        if row == []:
            continue
        if len(row) != len(columns):
            raise AppError("VALIDATION_FAILED", f"Row {line_no} has {len(row)} fields, expected {len(columns)}.")
        rows.append(row)

    return columns, rows


def typed_row(columns: list[str], row: list[str]) -> dict[str, Any]:
    """Parsed cell values. Empty cells are None, never zero or an empty string."""
    return {name: _typed(row[idx]) for idx, name in enumerate(columns)}


def parse_csv_bytes(data: bytes) -> ParsedDataset:
    """Validate a CSV upload and compute its profile. Raises AppError(VALIDATION_FAILED) on any problem."""
    columns, rows = read_table(data)
    columns_profile = []
    for idx, name in enumerate(columns):
        values = [r[idx] for r in rows]
        columns_profile.append({
            "name": name,
            "dtype": _infer_dtype(values),
            "nulls": sum(1 for v in values if _is_null(v)),
        })
    preview = [typed_row(columns, row) for row in rows[:PREVIEW_ROWS]]
    profile = {"rows": len(rows), "columns": columns_profile, "preview": preview}
    return ParsedDataset(size_bytes=len(data), sha256=sha256_bytes(data), profile=profile)


def dataset_file(data_dir: Path, storage_name: str) -> Path:
    if not _STORAGE_RE.match(storage_name):
        raise ValueError("invalid storage name")
    return data_dir / "datasets" / storage_name


def write_dataset_file(data_dir: Path, storage_name: str, data: bytes) -> Path:
    target = dataset_file(data_dir, storage_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target
