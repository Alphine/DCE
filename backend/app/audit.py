"""Append-only, hash-chained audit log (SDD 16.4). Writes must happen inside a transaction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.util import canonical_json, utc_now

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    checked: int
    first_invalid_id: int | None


def _row_hash(row_id: int, at: str, actor: str, action: str, subject: str | None,
              detail: Any, prev_hash: str) -> str:
    payload = {"id": row_id, "at": at, "actor": actor, "action": action,
               "subject": subject, "detail": detail, "prev_hash": prev_hash}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def append(conn: sqlite3.Connection, *, actor: str, action: str, subject: str | None,
           detail: dict[str, Any] | None = None) -> int:
    if not conn.in_transaction:
        raise RuntimeError("audit append requires an open transaction")
    detail = detail or {}
    last = conn.execute("SELECT id, row_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    prev_id = last["id"] if last else 0
    prev_hash = last["row_hash"] if last else GENESIS_HASH
    row_id = prev_id + 1
    at = utc_now()
    row_hash = _row_hash(row_id, at, actor, action, subject, detail, prev_hash)
    conn.execute(
        "INSERT INTO audit_logs (id, at, actor, action, subject, detail_json, prev_hash, row_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row_id, at, actor, action, subject, canonical_json(detail), prev_hash, row_hash),
    )
    return row_id


def verify(conn: sqlite3.Connection) -> VerifyResult:
    expected_prev = GENESIS_HASH
    expected_id = 1
    checked = 0
    for row in conn.execute("SELECT * FROM audit_logs ORDER BY id"):
        checked += 1
        detail = json.loads(row["detail_json"])
        recomputed = _row_hash(row["id"], row["at"], row["actor"], row["action"], row["subject"],
                               detail, row["prev_hash"])
        if row["id"] != expected_id or row["prev_hash"] != expected_prev or row["row_hash"] != recomputed:
            return VerifyResult(valid=False, checked=checked, first_invalid_id=row["id"])
        expected_prev = row["row_hash"]
        expected_id += 1
    return VerifyResult(valid=True, checked=checked, first_invalid_id=None)


def list_records(conn: sqlite3.Connection, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [
        {"id": r["id"], "at": r["at"], "actor": r["actor"], "action": r["action"], "subject": r["subject"],
         "detail": json.loads(r["detail_json"]), "prev_hash": r["prev_hash"], "row_hash": r["row_hash"]}
        for r in rows
    ]
