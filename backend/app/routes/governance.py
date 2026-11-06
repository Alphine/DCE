"""Health, dashboard summary, and audit routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app import audit
from app.auth import CurrentUser, current_user, require_role
from app.container import services_of
from app.util import utc_day

router = APIRouter(tags=["governance"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard/summary")
async def dashboard_summary(request: Request, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    services = services_of(request)
    settings = services.settings
    with services.db.read() as conn:
        datasets = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(status = 'APPROVED'), 0) AS approved FROM datasets").fetchone()
        by_state = {r["state"]: r["n"] for r in conn.execute(
            "SELECT state, COUNT(*) AS n FROM agent_tasks GROUP BY state")}
        artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        used = conn.execute("SELECT tasks_created FROM quota_usage WHERE user_id = ? AND day = ?",
                            (user.id, utc_day())).fetchone()
    try:
        running = int(await services.runner.running_count())
    except Exception:  # the dashboard must still load if the runner is unreachable
        running = 0
    model = services.planner.model_id
    return {
        "datasets": {"total": datasets["total"], "approved": datasets["approved"]},
        "tasks": {"by_state": by_state},
        "artifacts": artifacts,
        "sandbox": {"runner": services.runner.name, "max_concurrent": int(services.runner.max_concurrent),
                    "running": running},
        "inference": {"mode": settings.inference_mode, "model": model},
        "quota": {"used_today": int(used["tasks_created"]) if used else 0, "limit": settings.quota_tasks_per_day},
        "env": settings.env,
    }


@router.get("/audit")
def list_audit(request: Request, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
               user: CurrentUser = Depends(require_role("Reviewer"))) -> dict[str, Any]:
    with services_of(request).db.read() as conn:
        records = audit.list_records(conn, limit + 1, offset)  # one extra row tells us whether a next page exists
    has_more = len(records) > limit
    items = records[:limit]
    return {"items": items, "next_offset": offset + limit if has_more else None}


@router.post("/audit/verify")
def verify_audit(request: Request, user: CurrentUser = Depends(require_role("Admin"))) -> dict[str, Any]:
    services = services_of(request)
    with services.db.transaction() as conn:
        result = audit.verify(conn)
        audit.append(conn, actor=user.username, action="audit.verified", subject=None,
                     detail={"valid": result.valid, "checked": result.checked})
    return {"valid": result.valid, "checked": result.checked, "first_bad_id": result.first_invalid_id}
