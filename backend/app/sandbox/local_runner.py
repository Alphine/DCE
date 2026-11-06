"""LocalProcessRunner: DEVELOPMENT ONLY. Not isolated.

It runs task.py as a plain host subprocess in a fresh temp directory. It enforces a timeout, a stripped
environment, and output limits. It provides no containment: the code can read and write anything the
developer account can. It refuses to construct when DCE_ENV=production.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from app.sandbox.base import ArtifactFile, SandboxResult
from app.sandbox.errors import ArtifactRejected, SandboxConfigError
from app.sandbox.security import (
    ARTIFACT_RULES,
    OUTPUT_EXCERPT_BYTES,
    sha256_hex,
    validate_inputs,
    validate_script,
)
from app.sandbox.staging import stage_outputs
from app.sandbox.streams import excerpt, read_capped

logger = logging.getLogger(__name__)

_MAX_OUTPUT_FILES = 32
_warned = False


class LocalProcessRunner:
    name = "local"

    def __init__(
        self,
        *,
        env: str,
        staging_root: Path,
        timeout_s: int = 30,
        max_concurrent: int = 1,
    ) -> None:
        if env == "production":
            raise SandboxConfigError("LocalProcessRunner is development only and is disabled when DCE_ENV=production")
        global _warned
        if not _warned:
            logger.warning(
                "LocalProcessRunner is in use. It is NOT isolated and is for development only. "
                "Set DCE_SANDBOX_RUNNER=docker for any other use."
            )
            _warned = True
        self.max_concurrent = max_concurrent
        self._hard_timeout_s = timeout_s
        self._staging_root = staging_root
        self._slots = asyncio.Semaphore(max_concurrent)
        self._active: set[str] = set()

    async def running_count(self) -> int:
        return len(self._active)

    async def cancel(self, task_id: str) -> None:
        # Local processes are not tracked per task beyond the active set. Cancel is not supported here.
        logger.info("LocalProcessRunner.cancel(%s): no-op in development runner", task_id)

    async def sweep_orphans(self) -> int:
        return 0

    async def run(self, task_id: str, script: str, inputs: dict[str, bytes], timeout_s: int) -> SandboxResult:
        script_bytes = validate_script(script)
        validate_inputs(inputs)
        timeout = max(1, min(timeout_s, self._hard_timeout_s))
        code_sha = sha256_hex(script_bytes)

        async with self._slots:
            self._active.add(task_id)
            try:
                return await self._execute(task_id, script_bytes, code_sha, inputs, timeout)
            finally:
                self._active.discard(task_id)

    async def _execute(
        self,
        task_id: str,
        script_bytes: bytes,
        code_sha: str,
        inputs: dict[str, bytes],
        timeout: int,
    ) -> SandboxResult:
        started = time.monotonic()
        work = Path(tempfile.mkdtemp(prefix=f"dce-local-{task_id[:8]}-"))
        try:
            workspace = work / "workspace"
            (workspace / "out").mkdir(parents=True)
            for name, data in inputs.items():
                (workspace / name).write_bytes(data)
            (workspace / "task.py").write_bytes(script_bytes)

            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "task.py",
                cwd=str(workspace),
                env=_stripped_env(task_id, timeout),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timed_out = False
            out_task = asyncio.create_task(read_capped(proc.stdout, OUTPUT_EXCERPT_BYTES))
            err_task = asyncio.create_task(read_capped(proc.stderr, OUTPUT_EXCERPT_BYTES))
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                proc.kill()
                await proc.wait()
            (out_bytes, out_trunc), (err_bytes, err_trunc) = await asyncio.gather(out_task, err_task)

            exit_code = proc.returncode
            state = "TIMED_OUT" if timed_out else ("COMPLETED" if exit_code == 0 else "FAILED_SANDBOX")
            artifacts: list[ArtifactFile] = []
            if state == "COMPLETED":
                try:
                    artifacts = self._collect(task_id, workspace / "out")
                except ArtifactRejected as exc:
                    logger.warning("local run %s output rejected: %s", task_id, exc)
                    state = "FAILED_SANDBOX"

            return SandboxResult(
                task_id=task_id,
                state=state,
                runner="local",
                exit_code=exit_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=timed_out,
                oom_killed=False,
                container_id=None,
                stdout=excerpt(out_bytes),
                stderr=excerpt(err_bytes),
                stdout_truncated=out_trunc,
                stderr_truncated=err_trunc,
                code_sha256=code_sha,
                artifacts=artifacts,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _collect(self, task_id: str, out_dir: Path) -> list[ArtifactFile]:
        files: dict[str, bytes] = {}
        entries = list(os.scandir(out_dir))
        if len(entries) > _MAX_OUTPUT_FILES:
            raise ArtifactRejected(f"too many output files ({len(entries)})")
        for entry in entries:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise ArtifactRejected(f"non-regular output entry: {entry.name!r}")
            if entry.name not in ARTIFACT_RULES:
                raise ArtifactRejected(f"output name not allowlisted: {entry.name!r}")
            max_bytes = ARTIFACT_RULES[entry.name].max_bytes
            if entry.stat(follow_symlinks=False).st_size > max_bytes:
                raise ArtifactRejected(f"{entry.name} exceeds size limit")
            files[entry.name] = Path(entry.path).read_bytes()
        return stage_outputs(self._staging_root, task_id, files)


def _stripped_env(task_id: str, timeout_s: int) -> dict[str, str]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DCE_TASK_ID": task_id,
        "DCE_TIMEOUT_S": str(timeout_s),
    }
    if sys.platform == "win32" and "SYSTEMROOT" in os.environ:
        # Windows Python will not start without SYSTEMROOT.
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env
