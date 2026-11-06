"""Validate collected output files and write them to a host staging directory.

The backend copies staged files into DCE_DATA_DIR/artifacts/<task_id>/ and records their hashes.
Every file is validated before any file is written, so a rejected output set exports nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from app.sandbox.base import ArtifactFile
from app.sandbox.errors import ArtifactRejected
from app.sandbox.security import check_artifact, sha256_hex

_TASK_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def stage_outputs(staging_root: Path, task_id: str, files: Mapping[str, bytes]) -> list[ArtifactFile]:
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactRejected("task id is not a safe path component")

    for name, data in files.items():
        check_artifact(name, data)

    dest_dir = staging_root / task_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[ArtifactFile] = []
    for name in sorted(files):
        data = files[name]
        path = dest_dir / name  # name is an allowlisted constant by now
        path.write_bytes(data)
        artifacts.append(
            ArtifactFile(
                name=name,
                path=str(path.resolve()),
                sha256=sha256_hex(data),
                size_bytes=len(data),
            )
        )
    return artifacts
