"""Serialization of agent tasks to the AgentTask contract shape (docs/api.md section 3)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

SANDBOX_FIELDS = (
    "runner", "container_id", "exit_code", "duration_ms", "timed_out", "oom_killed",
    "stdout_excerpt", "stderr_excerpt", "stdout_truncated", "stderr_truncated",
)


def artifacts_visible(state: str, viewer_is_reviewer: bool) -> bool:
    """Owners see artifacts after COMPLETED. Reviewers also see them at gate B (SDD 7.7)."""
    if state == "COMPLETED":
        return True
    return viewer_is_reviewer and state == "AWAITING_REVIEW"


def artifact_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "name": row["name"],
        "type": row["type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "created_at": row["created_at"],
        "download_url": f"/api/artifacts/{row['id']}",
    }


def task_artifacts(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM artifacts WHERE task_id = ? ORDER BY name", (task_id,)).fetchall()
    return [artifact_view(r) for r in rows]


def task_view(conn: sqlite3.Connection, row: sqlite3.Row, viewer_is_reviewer: bool) -> dict[str, Any]:
    owner = conn.execute("SELECT id, username FROM users WHERE id = ?", (row["owner_id"],)).fetchone()
    approvals = conn.execute(
        "SELECT a.gate, a.decision, a.role, a.note, a.at, u.id AS approver_id, u.username "
        "FROM approvals a JOIN users u ON u.id = a.approver_id WHERE a.task_id = ? ORDER BY a.id",
        (row["id"],),
    ).fetchall()
    sandbox: dict[str, Any] | None = None
    if row["sandbox_json"]:
        stored = json.loads(row["sandbox_json"])
        sandbox = {key: stored.get(key) for key in SANDBOX_FIELDS}
    state = row["state"]
    return {
        "id": row["id"],
        "instruction": row["instruction"],
        "dataset_id": row["dataset_id"],
        "requested_outputs": json.loads(row["requested_outputs_json"]),
        "state": state,
        "plan": json.loads(row["plan_json"]) if row["plan_json"] else None,
        "code_sha256": row["code_sha256"],
        "sandbox": sandbox,
        "artifacts": task_artifacts(conn, row["id"]) if artifacts_visible(state, viewer_is_reviewer) else [],
        "approvals": [
            {
                "gate": a["gate"],
                "decision": a["decision"],
                "approver": {"id": a["approver_id"], "username": a["username"]},
                "role": a["role"],
                "at": a["at"],
                "note": a["note"],
            }
            for a in approvals
        ],
        "owner": {"id": owner["id"], "username": owner["username"]},
        "error_reason": row["error_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
