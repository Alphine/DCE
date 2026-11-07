"""Agent task state machine and background worker (docs/api.md section 4, SDD 7.6).

Route handlers are synchronous and run in the threadpool. Workers run as coroutines on the
application event loop; they are scheduled with run_coroutine_threadsafe. Every transition is
written in a transaction together with its audit record, and state events are published after commit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Coroutine

from app import audit
from app.agent.events import EventBus
from app.agent.outputs import OutputRejected, store_outputs, validate_outputs
from app.agent.planner import Planner, PlanningFailed
from app.agent.schemas import Plan
from app.agent.tools import DATASET_INPUT_NAMES, RULE_PACK_INPUT, TSUNAMI_PACK_INPUT, inputs_for_tools
from app.agent.views import task_view
from app.auth import CurrentUser
from app.config import Settings
from app.datasets import dataset_file
from app.db import Db
from app.errors import AppError
from app.rules.engine import PACK_HASH_FIELD, RulePackError, load_default_pack
from app.rules.tsunami import load_default_tsunami_pack
from app.util import new_id, sha256_bytes, utc_now

logger = logging.getLogger("dce.tasks")

MAX_LOG_LINES = 200
ORPHAN_CANDIDATES = ("PLANNING", "QUEUED", "RUNNING", "OUTPUT_VALIDATING")
TERMINAL_STATES = frozenset({"FAILED_PLANNING", "REJECTED", "CANCELLED", "TIMED_OUT", "FAILED_SANDBOX",
                             "REJECTED_OUTPUT", "COMPLETED", "ORPHANED"})

TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNING": frozenset({"AWAITING_APPROVAL", "FAILED_PLANNING", "ORPHANED"}),
    "AWAITING_APPROVAL": frozenset({"QUEUED", "REJECTED", "CANCELLED"}),
    "QUEUED": frozenset({"RUNNING", "CANCELLED", "FAILED_PLANNING", "ORPHANED"}),
    "RUNNING": frozenset({"OUTPUT_VALIDATING", "FAILED_SANDBOX", "TIMED_OUT", "CANCELLED", "ORPHANED"}),
    "OUTPUT_VALIDATING": frozenset({"AWAITING_REVIEW", "REJECTED_OUTPUT", "ORPHANED"}),
    "AWAITING_REVIEW": frozenset({"COMPLETED", "REJECTED_OUTPUT", "CANCELLED"}),
}
CANCELLABLE_STATES = frozenset({"QUEUED", "RUNNING", "AWAITING_APPROVAL", "AWAITING_REVIEW"})  # docs/api.md 12
GATE_A_ROLES = frozenset({"Approver", "Admin"})  # docs/api.md 12
_WRITABLE_COLUMNS = frozenset({"plan_json", "code_sha256", "sandbox_json", "error_reason"})


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise AppError("INVALID_STATE", f"A task in {current} cannot move to {target}.")


def seconds_between(earlier: str, later: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(later, fmt) - datetime.strptime(earlier, fmt)).total_seconds()


class TaskManager:
    def __init__(self, *, settings: Settings, db: Db, runner: Any, planner: Planner, bus: EventBus,
                 min_interval_s: float = 30.0) -> None:
        self.settings = settings
        self.db = db
        self.runner = runner
        self.planner = planner
        self.bus = bus
        self.min_interval_s = min_interval_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sem: asyncio.Semaphore | None = None
        self._background: set[asyncio.Future[Any]] = set()
        self._cancelling: set[str] = set()

    # ----- lifecycle -------------------------------------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._sem = asyncio.Semaphore(max(1, int(self.runner.max_concurrent)))
        self.bus.bind(loop)

    def recover(self) -> int:
        """Mark tasks left mid-flight by a previous process as ORPHANED (SDD 21.3). Never resumed."""
        with self.db.transaction() as conn:
            marks = ",".join("?" for _ in ORPHAN_CANDIDATES)
            rows = conn.execute(f"SELECT id, state FROM agent_tasks WHERE state IN ({marks})",
                                ORPHAN_CANDIDATES).fetchall()
            now = utc_now()
            for row in rows:
                conn.execute("UPDATE agent_tasks SET state = 'ORPHANED', error_reason = 'BACKEND_RESTART', "
                             "updated_at = ? WHERE id = ?", (now, row["id"]))
                _audit(conn, "system", "agent_task.state", row["id"],
                       {"from": row["state"], "to": "ORPHANED", "reason": "BACKEND_RESTART"})
        for row in rows:
            self.bus.publish(row["id"], "state", {"task_id": row["id"], "state": "ORPHANED", "at": utc_now()})
        return len(rows)

    async def sweep_sandbox(self) -> int:
        try:
            removed = int(await self.runner.sweep_orphans())
        except Exception:  # sandbox sweep failure must not block startup; it is audited
            logger.exception("sandbox sweep failed")
            removed = -1
        # The runner returns only a count, so each removal gets its own record without a container id.
        with self.db.transaction() as conn:
            for index in range(max(removed, 0)):
                _audit(conn, "system", "sandbox.orphan_removed", None,
                       {"runner": self.runner.name, "index": index + 1})
            _audit(conn, "system", "sandbox.sweep", None, {"runner": self.runner.name, "removed": removed})
        return removed

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        if self._loop is None:
            coro.close()
            raise RuntimeError("task manager is not bound to an event loop")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        self._background.add(future)
        future.add_done_callback(self._background.discard)

    def _run_sync(self, coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
        if self._loop is None:
            coro.close()
            raise RuntimeError("task manager is not bound to an event loop")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    # ----- public, called from route handlers ----------------------------------------------------

    def create_task(self, user: CurrentUser, *, instruction: str, dataset_id: str,
                    requested_outputs: list[str]) -> str:
        now = utc_now()
        task_id = new_id()
        day = now[:10]
        with self.db.transaction() as conn:
            last = conn.execute("SELECT MAX(created_at) AS last FROM agent_tasks WHERE owner_id = ?",
                                (user.id,)).fetchone()["last"]
            if last and seconds_between(last, now) < self.min_interval_s:
                raise AppError("RATE_LIMITED", "Wait before creating another agent task.",
                               headers={"Retry-After": str(int(self.min_interval_s))})
            dataset = conn.execute("SELECT id, status FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
            if dataset is None:
                raise AppError("NOT_FOUND", "Dataset not found.")
            if dataset["status"] != "APPROVED":
                raise AppError("FORBIDDEN", "Only approved datasets can be used by the agent.")
            used = conn.execute("SELECT tasks_created FROM quota_usage WHERE user_id = ? AND day = ?",
                                (user.id, day)).fetchone()
            used_count = int(used["tasks_created"]) if used else 0
            if used_count >= self.settings.quota_tasks_per_day:
                raise AppError("QUOTA_EXCEEDED", "Daily agent task quota reached.")
            conn.execute(
                "INSERT INTO quota_usage (user_id, day, tasks_created) VALUES (?, ?, 1) "
                "ON CONFLICT (user_id, day) DO UPDATE SET tasks_created = tasks_created + 1",
                (user.id, day),
            )
            conn.execute(
                "INSERT INTO agent_tasks (id, owner_id, instruction, dataset_id, requested_outputs_json, state, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'PLANNING', ?, ?)",
                (task_id, user.id, instruction, dataset_id, json.dumps(requested_outputs), now, now),
            )
            _audit(conn, user.username, "agent_task.created", task_id,
                   {"state": "PLANNING", "dataset_id": dataset_id})
        self._spawn(self._plan(task_id))
        return task_id

    def decide_gate(self, user: CurrentUser, task_id: str, gate: str, decision: str, note: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = _get_task(conn, task_id)
            state = row["state"]
            open_gate = {"AWAITING_APPROVAL": "A", "AWAITING_REVIEW": "B"}.get(state)
            if open_gate is None or open_gate != gate:
                raise AppError("INVALID_STATE", f"Gate {gate} is not open while the task is {state}.")
            if gate == "A" and user.role not in GATE_A_ROLES:
                raise AppError("FORBIDDEN", "Only an Approver or Admin may decide gate A.")
            if gate == "B" and not user.has_at_least("Reviewer"):
                raise AppError("FORBIDDEN", "Only a Reviewer or higher may decide gate B.")
            if row["owner_id"] == user.id:
                raise AppError("SELF_APPROVAL_NOT_ALLOWED", "You cannot approve your own agent task.")
            at = utc_now()
            conn.execute(
                "INSERT INTO approvals (task_id, gate, decision, approver_id, role, note, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, gate, decision, user.id, user.role, note, at),
            )
            _audit(conn, user.username, "gate.decision", task_id,
                   {"gate": gate, "decision": decision, "role": user.role})
            if gate == "A":
                target = "QUEUED" if decision == "approve" else "REJECTED"
            else:
                target = "COMPLETED" if decision == "approve" else "REJECTED_OUTPUT"
            self._write_transition(conn, task_id, target, actor=user.username, reason=None,
                                   requires=frozenset({state}))
        self.bus.publish(task_id, "gate", {"task_id": task_id, "gate": gate,
                                           "status": "approved" if decision == "approve" else "rejected"})
        self.bus.publish(task_id, "state", {"task_id": task_id, "state": target, "at": utc_now()})
        if target == "QUEUED":
            self._spawn(self._execute(task_id))
        elif target in TERMINAL_STATES:
            self.bus.publish(task_id, "end", {"task_id": task_id, "state": target})
        with self.db.read() as conn:
            return task_view(conn, _get_task(conn, task_id), user.has_at_least("Reviewer"))

    def cancel(self, user: CurrentUser, task_id: str) -> dict[str, Any]:
        with self.db.read() as conn:
            row = _get_task(conn, task_id)
        if row["owner_id"] != user.id and user.role != "Admin":
            raise AppError("FORBIDDEN", "Only the owner or an Admin can cancel this task.")
        if row["state"] not in CANCELLABLE_STATES:
            raise AppError("INVALID_STATE", f"A task in {row['state']} cannot be cancelled.")
        self._cancelling.add(task_id)  # tells the worker not to record a result for this run
        try:
            if row["state"] == "RUNNING":
                try:
                    self._run_sync(self.runner.cancel(task_id), timeout=40)  # kill the container first (SDD 7.6)
                except Exception:
                    logger.exception("runner cancel failed")
            with self.db.transaction() as conn:
                self._write_transition(conn, task_id, "CANCELLED", actor=user.username, reason=None,
                                       requires=CANCELLABLE_STATES, action="agent_task.cancelled")
        finally:
            self._cancelling.discard(task_id)
        self.bus.publish(task_id, "state", {"task_id": task_id, "state": "CANCELLED", "at": utc_now()})
        self.bus.publish(task_id, "end", {"task_id": task_id, "state": "CANCELLED"})
        with self.db.read() as conn:
            return task_view(conn, _get_task(conn, task_id), user.has_at_least("Reviewer"))

    # ----- workers ---------------------------------------------------------------------------------

    async def _plan(self, task_id: str) -> None:
        try:
            with self.db.read() as conn:
                row = _get_task(conn, task_id)
                dataset = conn.execute("SELECT name, profile_json, kind FROM datasets WHERE id = ?",
                                       (row["dataset_id"],)).fetchone()
            self.bus.publish(task_id, "log", _line("Planning started.", "system"))
            plan = await self.planner.create_plan(
                instruction=row["instruction"],
                requested_outputs=json.loads(row["requested_outputs_json"]),
                dataset_name=dataset["name"],
                profile=json.loads(dataset["profile_json"]),
                dataset_kind=dataset["kind"],
            )
            self._apply(task_id, "AWAITING_APPROVAL", actor="system",
                        plan_json=json.dumps(plan.model_dump(mode="json"), sort_keys=True))
            self.bus.publish(task_id, "log", _line("Plan validated; waiting for gate A.", "system"))
            self.bus.publish(task_id, "gate", {"task_id": task_id, "gate": "A", "status": "waiting"})
        except PlanningFailed as exc:
            self._fail(task_id, "PLANNING", "FAILED_PLANNING", exc.code)
        except AppError:
            logger.info("planning result discarded for task %s (state moved)", task_id)
        except Exception:
            logger.exception("planning crashed for task %s", task_id)
            self._fail(task_id, "PLANNING", "FAILED_PLANNING", "PLANNING_ERROR")

    async def _execute(self, task_id: str) -> None:
        assert self._sem is not None
        try:
            with self.db.read() as conn:
                row = _get_task(conn, task_id)
                if row["state"] != "QUEUED" or row["plan_json"] is None:
                    return
                plan = Plan.model_validate(json.loads(row["plan_json"]))
                dataset = conn.execute("SELECT profile_json, storage_name, kind FROM datasets WHERE id = ?",
                                       (row["dataset_id"],)).fetchone()
            profile = json.loads(dataset["profile_json"])
            script = await self.planner.create_script(plan, profile)
            self._apply(task_id, None, actor="system", requires=frozenset({"QUEUED"}),
                        action="agent_task.code_generated", code_sha256=sha256_bytes(script.encode("utf-8")),
                        extra={"model_id": self.planner.model_id})
            self.bus.publish(task_id, "log", _line("Code generated; waiting for a sandbox slot.", "system"))
        except PlanningFailed as exc:
            self._fail(task_id, "QUEUED", "FAILED_PLANNING", exc.code)
            return
        except AppError:
            return
        except Exception:
            logger.exception("code generation crashed for task %s", task_id)
            self._fail(task_id, "QUEUED", "FAILED_PLANNING", "CODE_GENERATION_ERROR")
            return

        async with self._sem:
            try:
                self._apply(task_id, "RUNNING", actor="system", requires=frozenset({"QUEUED"}))
            except AppError:
                return  # cancelled while waiting for a slot
            result, pack_hashes = await self._run_sandbox(task_id, plan, script, dataset_storage=dataset["storage_name"],
                                                          dataset_kind=dataset["kind"])
        await self._after_run(task_id, plan, result, pack_hashes=pack_hashes)

    async def _run_sandbox(self, task_id: str, plan: Plan, script: str, *, dataset_storage: str,
                           dataset_kind: str = "CSV") -> tuple[Any, dict[str, str]]:
        """Stage inputs and run. Returns (result, staged pack hashes keyed by "flood" and "tsunami")."""
        timeout = plan.limits.timeout_s
        try:
            data = dataset_file(self.settings.data_dir, dataset_storage).read_bytes()
        except OSError:
            return _synthetic_result(task_id, self.runner.name, "FAILED_SANDBOX", "DATASET_MISSING"), {}
        inputs: dict[str, bytes] = {DATASET_INPUT_NAMES[dataset_kind]: data}
        pack_hashes: dict[str, str] = {}
        needed = inputs_for_tools(plan.tools)
        # The server stages each rule pack a tool needs. A pack whose hash does not match is never staged.
        if RULE_PACK_INPUT in needed:
            try:
                pack_bytes, pack = load_default_pack()
            except RulePackError as exc:
                logger.warning("rule pack refused for task %s", task_id)
                return _synthetic_result(task_id, self.runner.name, "FAILED_SANDBOX", exc.code), {}
            inputs[RULE_PACK_INPUT] = pack_bytes
            pack_hashes["flood"] = pack[PACK_HASH_FIELD]
        if TSUNAMI_PACK_INPUT in needed:
            try:
                tsunami_bytes, tsunami_pack = load_default_tsunami_pack()
            except RulePackError as exc:
                logger.warning("tsunami rule pack refused for task %s", task_id)
                return _synthetic_result(task_id, self.runner.name, "FAILED_SANDBOX", exc.code), {}
            inputs[TSUNAMI_PACK_INPUT] = tsunami_bytes
            pack_hashes["tsunami"] = tsunami_pack[PACK_HASH_FIELD]
        self._audit_only(task_id, "sandbox.run_started", {"runner": self.runner.name, "timeout_s": timeout})
        self.bus.publish(task_id, "log", _line("Sandbox run started.", "system"))
        try:
            result = await asyncio.wait_for(
                self.runner.run(task_id, script, inputs, timeout), timeout=timeout + 15)
        except TimeoutError:
            result = _synthetic_result(task_id, self.runner.name, "TIMED_OUT", "SANDBOX_TIMEOUT", timed_out=True)
        except Exception:
            logger.exception("sandbox run crashed for task %s", task_id)
            result = _synthetic_result(task_id, self.runner.name, "FAILED_SANDBOX", "SANDBOX_ERROR")
        return result, pack_hashes

    async def _after_run(self, task_id: str, plan: Plan, result: Any, pack_hashes: dict[str, str] | None = None) -> None:
        if task_id in self._cancelling:
            return  # the cancel request owns the final state
        summary = _sandbox_summary(result)
        self._record_sandbox(task_id, summary)
        for stream, text in (("stdout", getattr(result, "stdout", "")), ("stderr", getattr(result, "stderr", ""))):
            for line in (text or "").splitlines()[:MAX_LOG_LINES]:
                self.bus.publish(task_id, "log", _line(line[:2000], stream))

        state = getattr(result, "state", "FAILED_SANDBOX")
        if state == "TIMED_OUT" or getattr(result, "timed_out", False):
            self._fail(task_id, "RUNNING", "TIMED_OUT", "SANDBOX_TIMEOUT")
            return
        if state != "COMPLETED" or getattr(result, "exit_code", 1) != 0:
            reason = str(summary.get("error_reason") or "SANDBOX_EXIT_NONZERO")
            self._fail(task_id, "RUNNING", "FAILED_SANDBOX", reason)
            return

        try:
            self._apply(task_id, "OUTPUT_VALIDATING", actor="system", requires=frozenset({"RUNNING"}))
        except AppError:
            return
        try:
            hashes = pack_hashes or {}
            verified = validate_outputs(result.artifacts, plan.expected_outputs, self.settings.data_dir,
                                        pack_sha256=hashes.get("flood"), tsunami_sha256=hashes.get("tsunami"))
            stored = store_outputs(verified, self.settings.data_dir, task_id)
        except OutputRejected as exc:
            logger.info("output rejected for task %s code=%s", task_id, exc.code)
            self._fail(task_id, "OUTPUT_VALIDATING", "REJECTED_OUTPUT", exc.code)
            return
        except Exception:
            logger.exception("output handling crashed for task %s", task_id)
            self._fail(task_id, "OUTPUT_VALIDATING", "REJECTED_OUTPUT", "OUTPUT_HANDLING_ERROR")
            return

        try:
            with self.db.transaction() as conn:
                now = utc_now()
                for item in stored:
                    conn.execute(
                        "INSERT INTO artifacts (id, task_id, name, type, size_bytes, sha256, storage_path, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (item["id"], task_id, item["name"], item["type"], item["size_bytes"], item["sha256"],
                         item["storage_path"], now),
                    )
                    _audit(conn, "system", "artifact.created", task_id, {
                        "artifact_id": item["id"], "type": item["type"],
                        "size_bytes": item["size_bytes"], "sha256": item["sha256"],
                    })
            self._apply(task_id, "AWAITING_REVIEW", actor="system", requires=frozenset({"OUTPUT_VALIDATING"}))
        except AppError:
            return
        self.bus.publish(task_id, "gate", {"task_id": task_id, "gate": "B", "status": "waiting"})

    # ----- helpers ---------------------------------------------------------------------------------

    def _fail(self, task_id: str, requires: str, target: str, reason: str) -> None:
        try:
            self._apply(task_id, target, actor="system", reason=reason, requires=frozenset({requires}))
        except AppError:
            logger.info("could not move task %s to %s (state moved)", task_id, target)

    def _apply(self, task_id: str, to_state: str | None, *, actor: str, reason: str | None = None,
               requires: frozenset[str] | None = None, action: str = "agent_task.state",
               extra: dict[str, Any] | None = None, **columns: str | None) -> None:
        """Single write path: transition (optional), column updates, audit, then publish after commit."""
        with self.db.transaction() as conn:
            self._write_transition(conn, task_id, to_state, actor=actor, reason=reason, requires=requires,
                                   action=action, extra=extra, columns=columns)
        if to_state is not None:
            self.bus.publish(task_id, "state", {"task_id": task_id, "state": to_state, "at": utc_now()})
            if to_state in TERMINAL_STATES:
                self.bus.publish(task_id, "end", {"task_id": task_id, "state": to_state})

    def _write_transition(self, conn: Any, task_id: str, to_state: str | None, *, actor: str,
                          reason: str | None = None, requires: frozenset[str] | None = None,
                          action: str = "agent_task.state", extra: dict[str, Any] | None = None,
                          columns: dict[str, str | None] | None = None) -> str:
        row = _get_task(conn, task_id)
        current = row["state"]
        if requires is not None and current not in requires:
            raise AppError("INVALID_STATE", f"The task is in {current}, which does not allow this action.")
        assignments: dict[str, Any] = {}
        if to_state is not None:
            check_transition(current, to_state)
            assignments["state"] = to_state
        for key, value in (columns or {}).items():
            if key not in _WRITABLE_COLUMNS:
                raise ValueError(f"column not writable: {key}")
            assignments[key] = value
        if reason is not None:
            assignments["error_reason"] = reason
        assignments["updated_at"] = utc_now()
        assignment_sql = ", ".join(f"{name} = ?" for name in assignments)
        conn.execute(f"UPDATE agent_tasks SET {assignment_sql} WHERE id = ?", (*assignments.values(), task_id))
        detail: dict[str, Any] = {"from": current, "to": to_state or current}
        if reason is not None:
            detail["reason"] = reason
        if extra:
            detail.update(extra)
        _audit(conn, actor, action, task_id, detail)
        return current

    def _record_sandbox(self, task_id: str, summary: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE agent_tasks SET sandbox_json = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(summary, sort_keys=True), utc_now(), task_id))
            _audit(conn, "system", "sandbox.run_finished", task_id, {
                "runner": summary.get("runner"), "container_id": summary.get("container_id"),
                "exit_code": summary.get("exit_code"), "timed_out": summary.get("timed_out"),
                "oom_killed": summary.get("oom_killed"), "duration_ms": summary.get("duration_ms"),
            })

    def _audit_only(self, task_id: str, action: str, detail: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            _audit(conn, "system", action, task_id, detail)

def _line(text: str, stream: str) -> dict[str, Any]:
    return {"stream": stream, "line": text, "at": utc_now()}


def _audit(conn: Any, actor: str, action: str, subject: str | None, detail: dict[str, Any]) -> None:
    audit.append(conn, actor=actor, action=action, subject=subject, detail=detail)


def _get_task(conn: Any, task_id: str) -> Any:
    row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Task not found.")
    return row


def _sandbox_summary(result: Any) -> dict[str, Any]:
    return {
        "runner": getattr(result, "runner", "unknown"),
        "container_id": getattr(result, "container_id", None),
        "exit_code": getattr(result, "exit_code", None),
        "duration_ms": int(getattr(result, "duration_ms", 0) or 0),
        "timed_out": bool(getattr(result, "timed_out", False)),
        "oom_killed": bool(getattr(result, "oom_killed", False)),
        "stdout_excerpt": (getattr(result, "stdout", "") or "")[: 64 * 1024],
        "stderr_excerpt": (getattr(result, "stderr", "") or "")[: 64 * 1024],
        "stdout_truncated": bool(getattr(result, "stdout_truncated", False)),
        "stderr_truncated": bool(getattr(result, "stderr_truncated", False)),
        "state": getattr(result, "state", "FAILED_SANDBOX"),
        "error_reason": getattr(result, "_error_reason", None),
    }


def _synthetic_result(task_id: str, runner: str, state: str, reason: str, timed_out: bool = False) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        task_id=task_id, runner=runner, state=state, exit_code=None, duration_ms=0, timed_out=timed_out,
        oom_killed=False, container_id=None, stdout="", stderr="", stdout_truncated=False,
        stderr_truncated=False, code_sha256="", artifacts=[], _error_reason=reason,
    )


