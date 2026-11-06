"""Artifact download with integrity check (SDD 17.3, 17.4)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app import audit
from app.agent.views import artifacts_visible
from app.auth import CurrentUser, current_user
from app.container import services_of
from app.errors import AppError
from app.util import sha256_file

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "png": "image/png",
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "py": "text/plain; charset=utf-8",
    "log": "text/plain; charset=utf-8",
}


@router.get("/{artifact_id}")
def download_artifact(artifact_id: str, request: Request, user: CurrentUser = Depends(current_user)) -> FileResponse:
    services = services_of(request)
    settings = services.settings
    with services.db.read() as conn:
        row = conn.execute(
            "SELECT a.*, t.owner_id, t.state FROM artifacts a JOIN agent_tasks t ON t.id = a.task_id WHERE a.id = ?",
            (artifact_id,),
        ).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Artifact not found.")
    reviewer = user.has_at_least("Reviewer")
    if row["owner_id"] != user.id and not reviewer:
        raise AppError("FORBIDDEN", "You may only download artifacts of your own tasks.")
    if not artifacts_visible(row["state"], reviewer):
        raise AppError("FORBIDDEN", "Artifacts are released after review.")

    data_root = Path(settings.data_dir).resolve()
    path = (data_root / row["storage_path"]).resolve()
    try:
        path.relative_to(data_root / "artifacts")
    except ValueError as exc:
        raise AppError("INTERNAL", "Artifact storage is misconfigured.") from exc
    if path.is_symlink() or not path.is_file():
        raise AppError("NOT_FOUND", "Artifact file is missing.")

    digest, _ = sha256_file(str(path))
    if digest != row["sha256"]:
        with services.db.transaction() as conn:
            audit.append(conn, actor=user.username, action="artifact.integrity_failed", subject=artifact_id,
                         detail={"task_id": row["task_id"]})
        raise AppError("CONFLICT", "Artifact integrity check failed. It has been flagged, not deleted.")

    with services.db.transaction() as conn:
        audit.append(conn, actor=user.username, action="artifact.downloaded", subject=artifact_id,
                     detail={"sha256": digest, "task_id": row["task_id"]})

    return FileResponse(
        path,
        media_type=CONTENT_TYPES[row["type"]],
        headers={
            "X-Content-SHA256": digest,
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{row["name"]}"',
            "Cache-Control": "no-store",
        },
    )
