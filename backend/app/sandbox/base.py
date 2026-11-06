"""Sandbox runner interface (docs/api.md section 6). Do not change without updating the contract."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ArtifactFile:
    name: str           # server-validated, e.g. "chart.png"
    path: str           # absolute path on the host, inside the data dir
    sha256: str
    size_bytes: int


@dataclass
class SandboxResult:
    task_id: str
    state: str          # "COMPLETED" | "FAILED_SANDBOX" | "TIMED_OUT"
    runner: str         # "docker" | "local"
    exit_code: int | None
    duration_ms: int
    timed_out: bool
    oom_killed: bool
    container_id: str | None
    stdout: str         # truncated to 64 KB by the runner
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    code_sha256: str
    artifacts: list[ArtifactFile] = field(default_factory=list)


class SandboxRunner(Protocol):
    name: str
    max_concurrent: int

    async def run(self, task_id: str, script: str,
                  inputs: dict[str, bytes], timeout_s: int) -> SandboxResult: ...

    async def cancel(self, task_id: str) -> None: ...

    async def sweep_orphans(self) -> int: ...      # returns number removed

    async def running_count(self) -> int: ...
