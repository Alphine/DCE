"""DockerSandboxRunner: runs generated code in a disposable, locked-down Docker container (SDD 9.2, 9.3).

Lifecycle per run:
  create (flags from 9.3) -> inspect and verify the security configuration -> start
  -> stage inputs by exec (stdin tar) -> wait for the worker to finish, bounded by the host watchdog
  -> read outputs (tar) -> validate and stage artifacts -> release the worker -> remove the container.

Why exec and not docker cp: /workspace is a tmpfs mount. Its contents exist only while the container
is running, so outputs must be read before the worker exits. docker exec runs inside the container's
mount namespace, so it reaches the tmpfs directly. The worker (PID 1) holds the container open until
the host has collected everything. See sandbox/worker.py.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import tarfile
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.sandbox.base import ArtifactFile, SandboxResult
from app.sandbox.errors import (
    ArtifactRejected,
    SandboxConfigError,
    SandboxInputError,
    SandboxSecurityError,
)
from app.sandbox.security import (
    ARTIFACT_RULES,
    MAX_OUTPUT_STREAM_BYTES,
    OUTPUT_EXCERPT_BYTES,
    sha256_hex,
    validate_inputs,
    validate_script,
)
from app.sandbox.staging import stage_outputs
from app.sandbox.streams import excerpt, read_capped
from app.sandbox.sweeper import orphan_threshold_s, parse_listing, select_orphans

logger = logging.getLogger(__name__)

# The repository root is backend/app/sandbox/docker_runner.py -> parents[3].
DEFAULT_SECCOMP_PATH = Path(__file__).resolve().parents[3] / "sandbox" / "seccomp" / "profile.json"

WORKER_CMD = ("python", "/sandbox/worker.py")
WORKSPACE = "/workspace"
TMPFS_WORKSPACE = "/workspace:rw,noexec,nosuid,size=100m,mode=1777"
RUN_UID_GID = "65534:65534"
NANO_CPUS = 1_000_000_000
NOFILE_LIMIT = 256
CLI_TIMEOUT_S = 30
KILL_WAIT_S = 15

_TASK_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_CID_RE = re.compile(r"^[0-9a-f]{12,64}$")
_TAR_OUT_PREFIX = "out/"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without Docker)
# ---------------------------------------------------------------------------

def build_create_argv(
    *,
    task_id: str,
    created_ts: int,
    image: str,
    memory_mb: int,
    pids: int,
    timeout_s: int,
    seccomp_path: Path,
) -> list[str]:
    """Arguments for `docker create` with the SDD 9.3 flag set. No bind mounts, no privilege, no host network."""
    mem = f"{memory_mb}m"
    return [
        "create",
        "--network", "none",
        "--read-only",
        "--tmpfs", TMPFS_WORKSPACE,
        "--cpus", "1",
        "--memory", mem,
        "--memory-swap", mem,
        "--pids-limit", str(pids),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--security-opt", f"seccomp={seccomp_path}",
        "--user", RUN_UID_GID,
        "--ulimit", f"nofile={NOFILE_LIMIT}:{NOFILE_LIMIT}",
        "--ipc", "none",
        "--label", f"dce.task={task_id}",
        "--label", f"dce.created={created_ts}",
        "--env", f"DCE_TASK_ID={task_id}",
        "--env", f"DCE_TIMEOUT_S={timeout_s}",
        image,
    ]


def verify_container_config(
    info: Mapping[str, Any],
    *,
    task_id: str,
    memory_mb: int,
    pids: int,
    seccomp_path: Path,
) -> list[str]:
    """Check `docker inspect` output against SDD 9.3. Returns violations; an empty list means verified."""
    hc: Mapping[str, Any] = info.get("HostConfig") or {}
    cfg: Mapping[str, Any] = info.get("Config") or {}
    labels: Mapping[str, Any] = cfg.get("Labels") or {}
    mem_bytes = memory_mb * 1024 * 1024
    problems: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            problems.append(msg)

    need(hc.get("NetworkMode") == "none", "NetworkMode is not none")
    need(hc.get("ReadonlyRootfs") is True, "ReadonlyRootfs is not true")
    need("ALL" in (hc.get("CapDrop") or []), "CapDrop does not contain ALL")
    need(not (hc.get("CapAdd") or []), "CapAdd is not empty")
    need(hc.get("Privileged") is False, "Privileged is not false")
    need(hc.get("PidsLimit") == pids, f"PidsLimit is not {pids}")
    need(not (hc.get("Binds") or []), "Binds is not empty")
    need(not (info.get("Mounts") or []), "container has mounts")
    need(hc.get("Memory") == mem_bytes, f"Memory is not {mem_bytes}")
    need(hc.get("MemorySwap") == mem_bytes, "MemorySwap does not equal Memory (swap not disabled)")
    need(hc.get("NanoCpus") == NANO_CPUS, "NanoCpus is not 1 CPU")
    need(hc.get("IpcMode") == "none", "IpcMode is not none")
    need(hc.get("PidMode") in ("", None, "private"), "PidMode is not private")
    need(hc.get("UsernsMode") != "host", "UsernsMode is host")

    sec_opts = [str(o) for o in (hc.get("SecurityOpt") or [])]
    need(any(o.split(":")[0] == "no-new-privileges" for o in sec_opts), "no-new-privileges not set")
    need(any(o.startswith("seccomp=") and o != "seccomp=unconfined" for o in sec_opts), "seccomp profile not set")

    tmpfs_opts = str((hc.get("Tmpfs") or {}).get(WORKSPACE, "")).split(",")
    need("noexec" in tmpfs_opts and "nosuid" in tmpfs_opts, "/workspace tmpfs lacks noexec,nosuid")

    nofile = [u for u in (hc.get("Ulimits") or []) if u.get("Name") == "nofile"]
    need(any(u.get("Soft") == NOFILE_LIMIT and u.get("Hard") == NOFILE_LIMIT for u in nofile),
         "nofile ulimit is not 256:256")

    need(cfg.get("User") == RUN_UID_GID, f"User is not {RUN_UID_GID}")
    need(labels.get("dce.task") == task_id, "dce.task label mismatch")
    return problems


def build_input_tar(script_bytes: bytes, inputs: Mapping[str, bytes], mtime: int) -> bytes:
    """Tar stream of task.py plus the approved inputs, owned by the run user. Piped to `worker.py stage`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        entries: dict[str, bytes] = {"task.py": script_bytes, **inputs}
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o444
            info.uid = info.gid = 65534
            info.uname = info.gname = "nobody"
            info.mtime = mtime
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def parse_output_tar(data: bytes) -> dict[str, bytes]:
    """Read the tar of /workspace/out produced by `worker.py emit`.

    Accepts only regular files named out/<allowlisted name>. Everything else is rejected.
    Member sizes are checked from headers before any content is read.
    """
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            for member in tar.getmembers():
                name = member.name[2:] if member.name.startswith("./") else member.name
                if member.isdir() and name.rstrip("/") == "out":
                    continue
                if not member.isreg():
                    raise ArtifactRejected(f"non-regular output entry: {member.name!r}")
                if not name.startswith(_TAR_OUT_PREFIX):
                    raise ArtifactRejected(f"output outside out/: {member.name!r}")
                base = name[len(_TAR_OUT_PREFIX):]
                if "/" in base or base in files:
                    raise ArtifactRejected(f"nested or duplicate output: {member.name!r}")
                rule = ARTIFACT_RULES.get(base)
                if rule is None:
                    raise ArtifactRejected(f"output name not allowlisted: {base!r}")
                if member.size > rule.max_bytes:
                    raise ArtifactRejected(f"{base} exceeds size limit")
                fh = tar.extractfile(member)
                if fh is None:
                    raise ArtifactRejected(f"unreadable output: {base!r}")
                files[base] = fh.read(rule.max_bytes + 1)
    except tarfile.TarError as exc:
        raise ArtifactRejected("output stream is not a valid tar") from exc
    return files


def _parse_rc(stdout: bytes) -> int | None:
    try:
        return int(stdout.decode("utf-8", errors="replace").strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class _Cli:
    rc: int
    stdout: bytes
    stdout_truncated: bool
    stderr: bytes
    stderr_truncated: bool


class _CliFailed(RuntimeError):
    pass


class DockerSandboxRunner:
    name = "docker"

    def __init__(
        self,
        *,
        image: str,
        staging_root: Path,
        memory_mb: int = 512,
        pids: int = 64,
        timeout_s: int = 30,
        max_concurrent: int = 1,
        seccomp_path: Path = DEFAULT_SECCOMP_PATH,
        docker_bin: str = "docker",
    ) -> None:
        if not seccomp_path.is_file():
            raise SandboxConfigError(f"seccomp profile not found: {seccomp_path}")
        if max_concurrent < 1:
            raise SandboxConfigError("max_concurrent must be at least 1")
        self._image = image
        self._staging_root = staging_root
        self._memory_mb = memory_mb
        self._pids = pids
        self._hard_timeout_s = timeout_s
        self._seccomp = seccomp_path
        self._docker = docker_bin
        self.max_concurrent = max_concurrent
        self._slots = asyncio.Semaphore(max_concurrent)
        self._active: dict[str, str] = {}  # task_id -> full container id

    async def running_count(self) -> int:
        return len(self._active)

    async def run(self, task_id: str, script: str, inputs: dict[str, bytes], timeout_s: int) -> SandboxResult:
        if not _TASK_ID_RE.fullmatch(task_id):
            raise SandboxInputError("task id has an unsafe format")
        script_bytes = validate_script(script)
        validate_inputs(inputs)
        timeout = max(1, min(int(timeout_s), self._hard_timeout_s))
        code_sha = sha256_hex(script_bytes)
        async with self._slots:
            return await self._run_locked(task_id, script_bytes, code_sha, inputs, timeout)

    async def cancel(self, task_id: str) -> None:
        cid = self._active.get(task_id)
        if cid:
            await self._kill(cid)
        # Also remove by label, which covers containers left behind by an earlier process.
        if _TASK_ID_RE.fullmatch(task_id):
            res = await self._cli_safe("ps", "-aq", "--no-trunc", "--filter", f"label=dce.task={task_id}")
            for cid_line in res.stdout.decode("utf-8", errors="replace").split():
                await self._remove(cid_line)

    async def sweep_orphans(self) -> int:
        listing = await self._cli_safe(
            "ps", "-a", "--no-trunc", "--filter", "label=dce.task",
            "--format", '{{.ID}}\t{{.Label "dce.created"}}',
        )
        if listing.rc != 0:
            logger.warning("orphan sweep: docker ps failed")
            return 0
        entries = parse_listing(listing.stdout.decode("utf-8", errors="replace"))
        victims = select_orphans(
            entries,
            now=int(time.time()),
            max_age_s=orphan_threshold_s(self._hard_timeout_s),
            active=set(self._active.values()),
        )
        removed = 0
        for cid in victims:
            if await self._remove(cid):
                removed += 1
                logger.warning("orphan sweep removed container %s", cid[:12])
        return removed

    # -- lifecycle ---------------------------------------------------------

    async def _run_locked(
        self,
        task_id: str,
        script_bytes: bytes,
        code_sha: str,
        inputs: dict[str, bytes],
        timeout: int,
    ) -> SandboxResult:
        started = time.monotonic()
        cid: str | None = None
        exit_task: asyncio.Task[_Cli] | None = None
        done_task: asyncio.Task[_Cli] | None = None
        timed_out = False
        oom = False
        exit_code: int | None = None
        script_rc: int | None = None
        artifacts: list[ArtifactFile] = []
        host_error: str | None = None

        try:
            cid = await self._create(task_id, timeout)
            self._active[task_id] = cid
            info = await self._inspect(cid)
            problems = verify_container_config(
                info, task_id=task_id, memory_mb=self._memory_mb, pids=self._pids, seccomp_path=self._seccomp,
            )
            if problems:
                raise SandboxSecurityError("security configuration not verified: " + "; ".join(problems))

            await self._cli_ok("start", cid, timeout=CLI_TIMEOUT_S)
            deadline = time.monotonic() + timeout
            exit_task = asyncio.create_task(self._cli("wait", cid, timeout=None))

            mtime = int(time.time())
            await self._cli_ok(
                "exec", "-i", cid, *WORKER_CMD, "stage",
                stdin=build_input_tar(script_bytes, inputs, mtime), timeout=CLI_TIMEOUT_S,
            )

            done_task = asyncio.create_task(self._cli("exec", cid, *WORKER_CMD, "await-done", timeout=None))
            finished, _ = await asyncio.wait(
                {done_task, exit_task},
                timeout=max(0.0, deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not finished:
                timed_out = True
                await self._kill(cid)
            elif done_task in finished and done_task.result().rc == 0:
                script_rc = _parse_rc(done_task.result().stdout)

            if script_rc == 0 and not timed_out:
                files = await self._emit(cid)
                artifacts = stage_outputs(self._staging_root, task_id, files)
            if script_rc is not None:
                await self._cli_safe("exec", cid, *WORKER_CMD, "release", timeout=CLI_TIMEOUT_S)

        except (SandboxSecurityError, SandboxInputError, ArtifactRejected, _CliFailed) as exc:
            host_error = str(exc)
            logger.warning("sandbox run %s failed on host side: %s", task_id, exc)
        except OSError as exc:
            host_error = f"docker CLI error: {type(exc).__name__}"
            logger.error("sandbox run %s: docker CLI error: %s", task_id, exc)
        except Exception as exc:  # any failure still destroys the container and returns a result
            host_error = f"unexpected host error: {type(exc).__name__}"
            logger.exception("sandbox run %s unexpected error", task_id)
        finally:
            if cid is not None:
                exit_code, oom, logs = await self._finish(cid, exit_task, done_task, graceful=script_rc is not None)
            else:
                exit_code, oom, logs = None, False, (b"", False, b"", False)
            logs_out, logs_out_t, logs_err, logs_err_t = logs
            if cid is not None:
                await self._remove(cid)
            self._active.pop(task_id, None)

        if timed_out:
            state = "TIMED_OUT"
        elif host_error is None and not oom and exit_code == 0 and script_rc == 0:
            state = "COMPLETED"
        else:
            state = "FAILED_SANDBOX"
            artifacts = []

        if host_error:
            note = f"\n[host] {host_error}".encode()
            logs_err = logs_err[: max(0, OUTPUT_EXCERPT_BYTES - len(note))] + note
            logs_err_t = logs_err_t or len(logs_err) > OUTPUT_EXCERPT_BYTES

        return SandboxResult(
            task_id=task_id,
            state=state,
            runner="docker",
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            oom_killed=oom,
            container_id=cid,
            stdout=excerpt(logs_out),
            stderr=excerpt(logs_err),
            stdout_truncated=logs_out_t,
            stderr_truncated=logs_err_t,
            code_sha256=code_sha,
            artifacts=artifacts,
        )

    async def _finish(
        self,
        cid: str,
        exit_task: asyncio.Task[_Cli] | None,
        done_task: asyncio.Task[_Cli] | None,
        *,
        graceful: bool,
    ) -> tuple[int | None, bool, tuple[bytes, bool, bytes, bool]]:
        """Stop the container if it is still held open, read its exit state and logs.

        graceful=True means the worker was released and is exiting on its own. Otherwise the container
        is still waiting for the host, so it is killed first.
        """
        if done_task is not None and not done_task.done():
            done_task.cancel()
        if exit_task is not None:
            if not graceful and not exit_task.done():
                await self._kill(cid)
            try:
                await asyncio.wait_for(asyncio.shield(exit_task), timeout=KILL_WAIT_S)
            except TimeoutError:
                await self._kill(cid)
                with suppress(TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(exit_task), timeout=KILL_WAIT_S)
            if not exit_task.done():
                exit_task.cancel()
        info = await self._inspect_safe(cid)
        exit_code, oom = _state_of(info)
        logs = await self._logs(cid)
        return exit_code, oom, logs

    async def _logs(self, cid: str) -> tuple[bytes, bool, bytes, bool]:
        res = await self._cli_safe("logs", cid, out_limit=OUTPUT_EXCERPT_BYTES, err_limit=OUTPUT_EXCERPT_BYTES)
        return res.stdout, res.stdout_truncated, res.stderr, res.stderr_truncated

    async def _emit(self, cid: str) -> dict[str, bytes]:
        res = await self._cli(
            "exec", cid, *WORKER_CMD, "emit",
            timeout=CLI_TIMEOUT_S, out_limit=MAX_OUTPUT_STREAM_BYTES,
        )
        if res.rc != 0:
            raise _CliFailed("output collection failed")
        if res.stdout_truncated:
            raise ArtifactRejected("output stream exceeds the size limit")
        return parse_output_tar(res.stdout)

    # -- docker CLI helpers -------------------------------------------------

    async def _create(self, task_id: str, timeout: int) -> str:
        argv = build_create_argv(
            task_id=task_id,
            created_ts=int(time.time()),
            image=self._image,
            memory_mb=self._memory_mb,
            pids=self._pids,
            timeout_s=timeout,
            seccomp_path=self._seccomp,
        )
        res = await self._cli(*argv, timeout=CLI_TIMEOUT_S)
        cid = res.stdout.decode("utf-8", errors="replace").strip()
        if res.rc != 0 or not _CID_RE.fullmatch(cid):
            raise _CliFailed("docker create failed: " + excerpt(res.stderr).strip())
        return cid

    async def _inspect(self, cid: str) -> dict[str, Any]:
        res = await self._cli("inspect", cid, timeout=CLI_TIMEOUT_S)
        if res.rc != 0:
            raise _CliFailed("docker inspect failed")
        data = json.loads(res.stdout.decode("utf-8"))
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise _CliFailed("docker inspect returned an unexpected shape")
        return data[0]

    async def _inspect_safe(self, cid: str) -> dict[str, Any]:
        try:
            return await self._inspect(cid)
        except (_CliFailed, ValueError, OSError):
            return {}

    async def _kill(self, cid: str) -> None:
        await self._cli_safe("kill", cid)

    async def _remove(self, cid: str) -> bool:
        res = await self._cli_safe("rm", "-f", cid)
        if res.rc != 0:
            logger.warning("docker rm -f %s failed", cid[:12])
        return res.rc == 0

    async def _cli_ok(self, *args: str, stdin: bytes | None = None, timeout: float | None) -> _Cli:
        res = await self._cli(*args, stdin=stdin, timeout=timeout)
        if res.rc != 0:
            raise _CliFailed(f"docker {args[0]} failed: " + excerpt(res.stderr).strip())
        return res

    async def _cli_safe(self, *args: str, **kwargs: Any) -> _Cli:
        """Like _cli, but a failure to run the CLI at all becomes a non-zero result, never an exception."""
        try:
            return await self._cli(*args, timeout=kwargs.pop("timeout", CLI_TIMEOUT_S), **kwargs)
        except (OSError, TimeoutError) as exc:
            logger.warning("docker %s could not complete: %s", args[0] if args else "?", type(exc).__name__)
            return _Cli(rc=-1, stdout=b"", stdout_truncated=False, stderr=b"", stderr_truncated=False)

    async def _cli(
        self,
        *args: str,
        timeout: float | None,
        stdin: bytes | None = None,
        out_limit: int = OUTPUT_EXCERPT_BYTES,
        err_limit: int = OUTPUT_EXCERPT_BYTES,
    ) -> _Cli:
        proc = await asyncio.create_subprocess_exec(
            self._docker, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async def feed() -> None:
                if stdin is None or proc.stdin is None:
                    return
                try:
                    proc.stdin.write(stdin)
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()

            gathered = asyncio.gather(
                read_capped(proc.stdout, out_limit),
                read_capped(proc.stderr, err_limit),
                feed(),
                proc.wait(),
            )
            (out, out_t), (err, err_t), _, _ = await asyncio.wait_for(gathered, timeout=timeout)
            return _Cli(rc=proc.returncode if proc.returncode is not None else -1,
                        stdout=out, stdout_truncated=out_t, stderr=err, stderr_truncated=err_t)
        except TimeoutError:
            with suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
        finally:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()


def _state_of(info: Mapping[str, Any]) -> tuple[int | None, bool]:
    state = info.get("State") or {}
    code = state.get("ExitCode")
    return (code if isinstance(code, int) else None), bool(state.get("OOMKilled"))
