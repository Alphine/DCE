"""Agent task routes: create, read, SSE events, gate decisions, cancel, artifacts (docs/api.md section 2, 5)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import sse_frame
from app.agent.task_manager import TERMINAL_STATES
from app.agent.views import artifacts_visible, task_artifacts, task_view
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.errors import AppError

router = APIRouter(prefix="/agent/tasks", tags=["agent"])
HEARTBEAT_S = 15.0


REQUESTED_OUTPUTS = frozenset({"affected_areas", "blocked_roads", "resource_requirements", "situation_report"})


class CreateTaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=2000)
    dataset_id: str = Field(min_length=36, max_length=36)
    requested_outputs: list[str] = Field(default_factory=list, max_length=4)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gate: Literal["A", "B"]
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


def _load_visible(request: Request, task_id: str, user: CurrentUser) -> dict[str, Any]:
    services = services_of(request)
    with services.db.read() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Task not found.")
        if row["owner_id"] != user.id and not user.has_at_least("Reviewer"):
            raise AppError("FORBIDDEN", "You may only view your own tasks.")
        return task_view(conn, row, user.has_at_least("Reviewer"))


@router.post("", status_code=202)
def create_task(body: CreateTaskBody, request: Request,
                user: CurrentUser = Depends(require_role("Analyst"))) -> JSONResponse:
    unknown = [name for name in body.requested_outputs if name not in REQUESTED_OUTPUTS]
    if unknown:
        raise AppError("VALIDATION_FAILED", "requested_outputs contains an unknown output name.", status=400)
    manager = services_of(request).manager
    task_id = manager.create_task(user, instruction=body.instruction, dataset_id=body.dataset_id,
                                  requested_outputs=body.requested_outputs)
    return JSONResponse({"task_id": task_id, "state": "PLANNING",
                         "events_url": f"/api/agent/tasks/{task_id}/events"}, status_code=202)


@router.get("")
def list_tasks(request: Request, user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    with services_of(request).db.read() as conn:
        if user.has_at_least("Reviewer"):
            rows = conn.execute("SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT 200").fetchall()
        else:
            rows = conn.execute("SELECT * FROM agent_tasks WHERE owner_id = ? ORDER BY created_at DESC LIMIT 200",
                                (user.id,)).fetchall()
        return [_summary(conn, r, user) for r in rows]


def _summary(conn: Any, row: Any, user: CurrentUser) -> dict[str, Any]:
    view = task_view(conn, row, user.has_at_least("Reviewer"))
    view["artifacts"] = view["artifacts"] if artifacts_visible(row["state"], user.has_at_least("Reviewer")) else []
    return view


@router.get("/{task_id}")
def get_task(task_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return _load_visible(request, task_id, user)


@router.get("/{task_id}/events")
async def task_events(task_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> StreamingResponse:
    services = services_of(request)
    _load_visible(request, task_id, user)  # authorization before subscribing
    queue = services.bus.subscribe(task_id)

    async def stream() -> AsyncIterator[str]:
        try:
            with services.db.read() as conn:
                row = conn.execute("SELECT state, updated_at FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
            current = row["state"]
            yield sse_frame("state", {"task_id": task_id, "state": current, "at": row["updated_at"]})
            if current == "AWAITING_APPROVAL":
                yield sse_frame("gate", {"task_id": task_id, "gate": "A", "status": "waiting"})
            elif current == "AWAITING_REVIEW":
                yield sse_frame("gate", {"task_id": task_id, "gate": "B", "status": "waiting"})
            if current in TERMINAL_STATES:
                yield sse_frame("end", {"task_id": task_id, "state": current})
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield sse_frame(event, data)
                if event == "end":
                    return
        finally:
            services.bus.unsubscribe(task_id, queue)

    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


@router.post("/{task_id}/approve")
def decide(task_id: str, body: DecisionBody, request: Request,
           user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    # The manager checks that the named gate is open and that the caller's role and ownership allow it.
    return services_of(request).manager.decide_gate(user, task_id, body.gate, body.decision, body.note)


@router.post("/{task_id}/cancel")
def cancel(task_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return services_of(request).manager.cancel(user, task_id)


@router.get("/{task_id}/artifacts")
def list_artifacts(task_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    services = services_of(request)
    with services.db.read() as conn:
        row = conn.execute("SELECT owner_id, state FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Task not found.")
        reviewer = user.has_at_least("Reviewer")
        if row["owner_id"] != user.id and not reviewer:
            raise AppError("FORBIDDEN", "You may only view your own tasks.")
        if not artifacts_visible(row["state"], reviewer):
            return []
        return task_artifacts(conn, task_id)
