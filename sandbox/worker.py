"""Sandbox worker. Runs inside the container as PID 1 (user 65534) and as short-lived `docker exec` helpers.

Modes:
  (no args)     run: wait for .go, execute /workspace/task.py, write .done, wait for .collected, exit with the
                task's code. Staying alive keeps the tmpfs /workspace available while the host collects outputs.
  stage         exec, reads a tar from stdin: task.py and input files into /workspace, then writes .go.
  await-done    exec, waits for .done and prints the task's exit code.
  emit          exec, writes /workspace/out regular files to stdout as a tar (out/<name>).
  release       exec, writes .collected so the run mode can exit.

The worker needs no network and no environment variables beyond the allowlist. Isolation comes from the container.
"""

from __future__ import annotations

import os
import re
import runpy
import stat
import sys
import tarfile
import time
import traceback

WORKSPACE = "/workspace"
OUT_DIR = os.path.join(WORKSPACE, "out")
TASK_NAME = "task.py"
GO_FILE = os.path.join(WORKSPACE, ".go")
DONE_FILE = os.path.join(WORKSPACE, ".done")
COLLECTED_FILE = os.path.join(WORKSPACE, ".collected")

MAX_STAGE_BYTES = 10 * 1024 * 1024
WAIT_CAP_S = 1200.0
POLL_S = 0.05
INPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _fail(message: str) -> int:
    print(f"worker: {message}", file=sys.stderr)
    return 1


def _wait_for(path: str) -> None:
    deadline = time.monotonic() + WAIT_CAP_S
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {os.path.basename(path)}")
        time.sleep(POLL_S)


def _execute_task() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.chdir(WORKSPACE)
    try:
        runpy.run_path(os.path.join(WORKSPACE, TASK_NAME), run_name="__main__")
        return 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    except BaseException:  # includes SyntaxError from a malformed script
        traceback.print_exc()
        return 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()


def run_mode() -> int:
    _wait_for(GO_FILE)
    rc = _execute_task()
    with open(DONE_FILE, "w", encoding="utf-8") as fh:
        fh.write(str(rc))
    _wait_for(COLLECTED_FILE)
    return rc


def stage_mode() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    seen: set[str] = set()
    total = 0
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
        for member in tar:
            name = member.name
            if not member.isreg():
                return _fail("staging accepts regular files only")
            if name != TASK_NAME and (name == "out" or not INPUT_NAME_RE.fullmatch(name)):
                return _fail(f"staging name rejected: {name!r}")
            if name in seen:
                return _fail(f"duplicate staging name: {name!r}")
            total += member.size
            if total > MAX_STAGE_BYTES:
                return _fail("staging exceeds size limit")
            fh = tar.extractfile(member)
            if fh is None:
                return _fail(f"unreadable staging entry: {name!r}")
            data = fh.read(member.size)
            with open(os.path.join(WORKSPACE, name), "xb") as out:
                out.write(data)
            seen.add(name)
    if TASK_NAME not in seen:
        return _fail("task.py was not staged")
    with open(GO_FILE, "w", encoding="utf-8") as fh:
        fh.write("go")
    return 0


def await_done_mode() -> int:
    _wait_for(DONE_FILE)
    with open(DONE_FILE, encoding="utf-8") as fh:
        print(fh.read().strip())
    return 0


def emit_mode() -> int:
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
        for name in sorted(os.listdir(OUT_DIR)):
            path = os.path.join(OUT_DIR, name)
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode):
                return _fail(f"non-regular output entry: {name!r}")
            info = tarfile.TarInfo(name=f"out/{name}")
            info.size = st.st_size
            info.mode = 0o644
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    sys.stdout.buffer.flush()
    return 0


def release_mode() -> int:
    with open(COLLECTED_FILE, "w", encoding="utf-8") as fh:
        fh.write("ok")
    return 0


_MODES = {
    "run": run_mode,
    "stage": stage_mode,
    "await-done": await_done_mode,
    "emit": emit_mode,
    "release": release_mode,
}


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "run"
    handler = _MODES.get(mode)
    if handler is None:
        return _fail(f"unknown mode: {mode!r}")
    try:
        return handler()
    except Exception as exc:  # helper modes report a clean error; the host decides the outcome
        return _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
