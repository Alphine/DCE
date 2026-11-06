"""Select the sandbox runner from settings (docs/api.md section 7, DCE_SANDBOX_RUNNER).

Settings attributes read here map to the DCE_* variables in docs/api.md section 9:
  env, data_dir, sandbox_runner, sandbox_image, sandbox_max_concurrent,
  sandbox_timeout_s, sandbox_memory_mb, sandbox_pids.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.sandbox.base import SandboxRunner
from app.sandbox.docker_runner import DockerSandboxRunner
from app.sandbox.errors import SandboxConfigError
from app.sandbox.local_runner import LocalProcessRunner

STAGING_DIR_NAME = "sandbox_staging"


def make_runner(settings: Any) -> SandboxRunner:
    kind = str(settings.sandbox_runner).strip().lower()
    staging_root = Path(settings.data_dir) / STAGING_DIR_NAME

    if kind == "docker":
        return DockerSandboxRunner(
            image=settings.sandbox_image,
            staging_root=staging_root,
            memory_mb=settings.sandbox_memory_mb,
            pids=settings.sandbox_pids,
            timeout_s=settings.sandbox_timeout_s,
            max_concurrent=settings.sandbox_max_concurrent,
        )
    if kind == "local":
        return LocalProcessRunner(
            env=settings.env,
            staging_root=staging_root,
            timeout_s=settings.sandbox_timeout_s,
            max_concurrent=settings.sandbox_max_concurrent,
        )
    raise SandboxConfigError(f"unknown DCE_SANDBOX_RUNNER: {kind!r} (expected 'docker' or 'local')")
