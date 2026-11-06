"""Task state machine, gates, quota, output validation, orphan recovery, SSE, artifacts, and audit."""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

import pytest

from app.agent.task_manager import TRANSITIONS, check_transition
from app.errors import AppError
from app.util import new_id, utc_now
from app.audit import verify as verify_audit
from tests.conftest import Env


def _happy_task(env: Env) -> str:
    """Create a task and drive it to AWAITING_REVIEW through gate A."""
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    response = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"),
                       json={"gate": "A", "decision": "approve", "note": "ok"})
    assert response.status_code == 200, response.text
    env.wait_state(task_id, {"AWAITING_REVIEW"}, as_user="analyst")
    return task_id


def test_state_transition_table() -> None:
    check_transition("PLANNING", "AWAITING_APPROVAL")
    check_transition("AWAITING_REVIEW", "COMPLETED")
    with pytest.raises(AppError) as exc:
        check_transition("PLANNING", "COMPLETED")
    assert exc.value.code == "INVALID_STATE"
    with pytest.raises(AppError):
        check_transition("AWAITING_APPROVAL", "RUNNING")  # gate A must come first
    for terminal in ("COMPLETED", "REJECTED", "REJECTED_OUTPUT", "FAILED_PLANNING", "FAILED_SANDBOX",
                     "TIMED_OUT", "CANCELLED", "ORPHANED"):
        assert TRANSITIONS.get(terminal, frozenset()) == frozenset()


def test_happy_path_through_both_gates(logged_in: Env) -> None:
    env = logged_in
    task_id = _happy_task(env)
    task = env.api("GET", f"/api/agent/tasks/{task_id}", env.token("analyst")).json()
    assert task["state"] == "AWAITING_REVIEW"
    assert task["code_sha256"] and len(task["code_sha256"]) == 64
    assert task["sandbox"]["runner"] == "local"
    assert task["artifacts"] == [], "owner must not see artifacts before COMPLETED"
    assert [a["gate"] for a in task["approvals"]] == ["A"]

    reviewer_view = env.api("GET", f"/api/agent/tasks/{task_id}", env.token("reviewer")).json()
    assert {a["name"] for a in reviewer_view["artifacts"]} == {"summary.json", "situation_report.md"}

    # The generated script is what the runner received, and only dataset.csv is staged.
    call = env.runner.calls[-1]
    assert call["inputs"] == ["dataset.csv"]
    assert "dataset.csv" in call["script"]

    # Gate B: an Analyst may not release; a Reviewer may.
    assert env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("analyst"),
                   json={"gate": "B", "decision": "approve"}).status_code == 403
    done = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("reviewer"),
                   json={"gate": "B", "decision": "approve"})
    assert done.status_code == 200
    assert done.json()["state"] == "COMPLETED"
    owner_view = env.api("GET", f"/api/agent/tasks/{task_id}", env.token("analyst")).json()
    assert len(owner_view["artifacts"]) == 2


def test_self_approval_refused_at_gate_a(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("approver")  # Approver may create tasks (rank above Analyst)
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="approver")
    response = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"),
                       json={"gate": "A", "decision": "approve"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_NOT_ALLOWED"


def test_invalid_transitions_return_409(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    gate_b = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("reviewer"),
                     json={"gate": "B", "decision": "approve"})
    assert gate_b.status_code == 409
    assert gate_b.json()["error"]["code"] == "INVALID_STATE"
    assert gate_b.json()["error"]["request_id"].startswith("req_")
    # Gate A is still open, so cancel is allowed (docs/api.md 12). Cancelling again is a terminal-state check.
    cancel = env.api("POST", f"/api/agent/tasks/{task_id}/cancel", env.token("analyst"))
    assert cancel.status_code == 200
    assert cancel.json()["state"] == "CANCELLED"
    again = env.api("POST", f"/api/agent/tasks/{task_id}/cancel", env.token("analyst"))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE"


def test_gate_a_reject_is_terminal_and_streams_end(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    response = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"),
                       json={"gate": "A", "decision": "reject", "note": "no"})
    assert response.json()["state"] == "REJECTED"
    with env.client.stream("GET", f"/api/agent/tasks/{task_id}/events",
                           headers={"Cookie": f"dce_session={env.token('analyst')}"}) as stream:
        body = b"".join(stream.iter_bytes()).decode("utf-8")
    assert "event: state" in body
    assert "event: end" in body
    assert '"state": "REJECTED"' in body or '"state":"REJECTED"' in body


def test_cancel_is_only_for_owner_or_admin(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    other = env.api("POST", f"/api/agent/tasks/{task_id}/cancel", env.token("reviewer"))
    assert other.status_code == 403


def test_cancel_running_task_kills_then_sets_state(make_env: Callable[..., Env]) -> None:
    env = make_env(runner_mode="hang")
    for u in ("analyst", "approver"):
        env.login(u)
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"), json={"gate": "A", "decision": "approve"})
    env.wait_state(task_id, {"RUNNING"}, as_user="analyst")
    response = env.api("POST", f"/api/agent/tasks/{task_id}/cancel", env.token("analyst"))
    assert response.status_code == 200
    assert response.json()["state"] == "CANCELLED"
    assert env.runner.cancelled == [task_id]


@pytest.mark.parametrize("mode, expected_state, expected_reason", [
    ("sandbox_fail", "FAILED_SANDBOX", None),
    ("bad_json", "REJECTED_OUTPUT", "OUTPUT_TYPE_MISMATCH"),
    ("missing_summary", "REJECTED_OUTPUT", "OUTPUT_MISSING"),
])
def test_bad_runs_end_in_failure_states(make_env: Callable[..., Env], mode: str, expected_state: str,
                                        expected_reason: str | None) -> None:
    env = make_env(runner_mode=mode)
    for u in ("analyst", "approver"):
        env.login(u)
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"), json={"gate": "A", "decision": "approve"})
    task = env.wait_state(task_id, {expected_state}, as_user="analyst")
    if expected_reason:
        assert task["error_reason"] == expected_reason


def test_planning_failure_reaches_failed_planning(make_env: Callable[..., Env]) -> None:
    from app.agent.inference_client import InferenceError

    class BadPlanner:
        model_id = "bad"

        async def plan(self, request: object) -> dict:
            raise InferenceError("MODEL_OUTPUT_INVALID", "not json")

        async def generate_code(self, plan: dict, profile: dict) -> str:
            return ""

    env = make_env(inference=BadPlanner())
    env.login("analyst")
    task_id = env.create_task("analyst")
    task = env.wait_state(task_id, {"FAILED_PLANNING"}, as_user="analyst")
    assert task["error_reason"] == "MODEL_OUTPUT_INVALID"


def test_daily_quota_is_enforced(make_env: Callable[..., Env]) -> None:
    env = make_env(quota_tasks_per_day=2, min_interval_s=0.0)
    env.login("analyst")
    dataset_id = env.approved_dataset()
    for _ in range(2):
        assert env.api("POST", "/api/agent/tasks", env.token("analyst"), json={
            "instruction": "analyze", "dataset_id": dataset_id}).status_code == 202
    third = env.api("POST", "/api/agent/tasks", env.token("analyst"), json={
        "instruction": "analyze", "dataset_id": dataset_id})
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "QUOTA_EXCEEDED"


def test_creation_interval_is_enforced(make_env: Callable[..., Env]) -> None:
    env = make_env(min_interval_s=30.0)
    env.login("analyst")
    dataset_id = env.approved_dataset()
    body = {"instruction": "analyze", "dataset_id": dataset_id}
    assert env.api("POST", "/api/agent/tasks", env.token("analyst"), json=body).status_code == 202
    second = env.api("POST", "/api/agent/tasks", env.token("analyst"), json=body)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_unapproved_dataset_cannot_be_used(logged_in: Env) -> None:
    dataset_id = logged_in.upload("analyst").json()["id"]
    response = logged_in.api("POST", "/api/agent/tasks", logged_in.token("analyst"), json={
        "instruction": "analyze", "dataset_id": dataset_id})
    assert response.status_code == 403


def test_viewer_cannot_create_tasks(logged_in: Env) -> None:
    dataset_id = logged_in.approved_dataset()
    response = logged_in.api("POST", "/api/agent/tasks", logged_in.token("viewer"), json={
        "instruction": "analyze", "dataset_id": dataset_id})
    assert response.status_code == 403


def test_orphan_recovery_on_restart(make_env: Callable[..., Env]) -> None:
    env = make_env()
    env.login("analyst")
    dataset_id = env.approved_dataset()
    task_id = new_id()
    with env.db.transaction() as conn:
        conn.execute(
            "INSERT INTO agent_tasks (id, owner_id, instruction, dataset_id, requested_outputs_json, state, "
            "created_at, updated_at) SELECT ?, id, 'x', ?, '[]', 'RUNNING', ?, ? FROM users WHERE username='analyst'",
            (task_id, dataset_id, utc_now(), utc_now()))
    # Restart with the same database: lifespan reconciles mid-flight tasks.
    env.client.__exit__(None, None, None)
    restarted = make_env(seed=False, settings=env.settings)
    restarted.login("analyst")
    task = restarted.api("GET", f"/api/agent/tasks/{task_id}", restarted.token("analyst")).json()
    assert task["state"] == "ORPHANED"
    assert task["error_reason"] == "BACKEND_RESTART"


def test_sse_replays_current_state_for_pending_gate(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("analyst")
    env.wait_state(task_id, {"AWAITING_APPROVAL"}, as_user="analyst")
    with env.client.stream("GET", f"/api/agent/tasks/{task_id}/events",
                           headers={"Cookie": f"dce_session={env.token('analyst')}"}) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines: list[str] = []
        for line in stream.iter_lines():
            lines.append(line)
            if line.startswith("event: gate"):
                break
    assert any(line == "event: state" for line in lines)
    assert any(line == "event: gate" for line in lines)


def test_events_forbidden_to_other_viewers(logged_in: Env) -> None:
    env = logged_in
    task_id = env.create_task("analyst")
    response = env.api("GET", f"/api/agent/tasks/{task_id}/events", env.token("viewer"))
    assert response.status_code == 403


def test_artifact_download_headers_and_integrity(logged_in: Env) -> None:
    env = logged_in
    task_id = _happy_task(env)
    env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("reviewer"), json={"gate": "B", "decision": "approve"})
    artifacts = env.api("GET", f"/api/agent/tasks/{task_id}/artifacts", env.token("analyst")).json()
    summary = next(a for a in artifacts if a["name"] == "summary.json")
    response = env.api("GET", summary["download_url"], env.token("analyst"))
    assert response.status_code == 200
    assert response.headers["x-content-sha256"] == summary["sha256"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")
    assert json.loads(response.content)["flooded_rows"] == 2

    # Tamper with the stored file: the download is refused and flagged.
    path = next((env.settings.data_dir / "artifacts").rglob(f"*.json"))
    path.write_bytes(b'{"flooded_rows": 999}')
    tampered = env.api("GET", summary["download_url"], env.token("analyst"))
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "CONFLICT"


def test_artifact_not_visible_to_non_owner_viewer(logged_in: Env) -> None:
    env = logged_in
    task_id = _happy_task(env)
    env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("reviewer"), json={"gate": "B", "decision": "approve"})
    artifacts = env.api("GET", f"/api/agent/tasks/{task_id}/artifacts", env.token("analyst")).json()
    response = env.api("GET", artifacts[0]["download_url"], env.token("viewer"))
    assert response.status_code == 403


def test_audit_chain_verifies_and_detects_tampering(logged_in: Env) -> None:
    env = logged_in
    _happy_task(env)
    verify = env.api("POST", "/api/audit/verify", env.token("admin"))
    assert verify.status_code == 200
    assert verify.json()["valid"] is True
    assert verify.json()["first_bad_id"] is None
    assert verify.json()["checked"] > 5

    assert env.api("POST", "/api/audit/verify", env.token("analyst")).status_code == 403
    page = env.api("GET", "/api/audit?limit=5", env.token("reviewer")).json()
    records = page["items"]
    assert page["next_offset"] == 5
    assert len(records) == 5 and len(records[0]["row_hash"]) == 64
    assert env.api("GET", "/api/audit", env.token("analyst")).status_code == 403

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with env.db.transaction() as conn:
            conn.execute("UPDATE audit_logs SET action = 'x' WHERE id = 1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with env.db.transaction() as conn:
            conn.execute("DELETE FROM audit_logs WHERE id = 1")

    # Simulate an attacker who drops the trigger and edits a row: the hash chain must catch it.
    with env.db.transaction() as conn:
        conn.execute("DROP TRIGGER audit_logs_no_update")
        conn.execute("UPDATE audit_logs SET actor = 'mallory' WHERE id = 3")
    with env.db.transaction() as conn:
        result = verify_audit(conn)
    assert result.valid is False
    assert result.first_invalid_id == 3


def test_requested_outputs_outside_the_four_names_return_400(logged_in: Env) -> None:
    dataset_id = logged_in.approved_dataset()
    response = logged_in.api("POST", "/api/agent/tasks", logged_in.token("analyst"), json={
        "instruction": "analyze", "dataset_id": dataset_id, "requested_outputs": ["shell_exec"]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_dataset_rows_pagination_and_nulls(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.approved_dataset()
    first = env.api("GET", f"/api/datasets/{dataset_id}/rows?limit=4&offset=0", env.token("viewer")).json()
    assert first["total"] == 6
    assert first["next_offset"] == 4
    assert len(first["items"]) == 4
    assert first["items"][1] == {"district": "Cilandak", "water_depth_cm": None, "road_status": "open",
                                 "affected_population": 80, "reported_at": None}
    second = env.api("GET", f"/api/datasets/{dataset_id}/rows?limit=4&offset=4", env.token("viewer")).json()
    assert second["next_offset"] is None
    assert len(second["items"]) == 2
    assert env.api("GET", f"/api/datasets/{dataset_id}/rows?limit=1001", env.token("viewer")).status_code == 422


def test_unapproved_dataset_rows_hidden_from_viewers(logged_in: Env) -> None:
    env = logged_in
    dataset_id = env.upload("analyst").json()["id"]
    assert env.api("GET", f"/api/datasets/{dataset_id}/rows", env.token("viewer")).status_code == 404
    assert env.api("GET", f"/api/datasets/{dataset_id}/rows", env.token("analyst")).status_code == 200
