"""Hostile-workload cases from SDD 9.8 (T01 to T12).

Local cases (no marker) run through LocalProcessRunner. This runner is NOT isolated, so only behaviour that does
not depend on isolation is asserted here: result shape, timeouts, syntax errors, output rules, and environment
stripping. Isolation cases are marked `docker`. They run the real worker image through DockerSandboxRunner and
are meant for the Vultr VM, with DCE_TEST_DOCKER=1 and DCE_SANDBOX_IMAGE set to the pinned image.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from app.sandbox.docker_runner import DEFAULT_SECCOMP_PATH, DockerSandboxRunner
from app.sandbox.local_runner import LocalProcessRunner


def _local(tmp_path: Path) -> LocalProcessRunner:
    return LocalProcessRunner(env="development", staging_root=tmp_path / "staging", timeout_s=5)


def _run_local(tmp_path: Path, script: str, timeout_s: int = 5):
    runner = _local(tmp_path)
    return asyncio.run(runner.run(str(uuid.uuid4()), script, {}, timeout_s))


# -- T01: normal execution -----------------------------------------------------

def test_T01_normal_python_execution_completes_with_artifact(tmp_path: Path) -> None:
    script = (
        "import json, pathlib\n"
        "rows = [l.split(',') for l in open('flood.csv').read().splitlines()[1:]]\n"
        "flooded = [r[0] for r in rows if float(r[1]) > 30]\n"
        "pathlib.Path('out/summary.json').write_text(json.dumps({'flooded_districts': flooded}))\n"
    )
    runner = _local(tmp_path)
    result = asyncio.run(runner.run(str(uuid.uuid4()), script,
                                    {"flood.csv": b"district,water_depth_cm\nKemang,35\nMenteng,12\n"}, 5))
    assert result.state == "COMPLETED", result.stderr
    assert result.exit_code == 0
    assert [a.name for a in result.artifacts] == ["summary.json"]


# -- T02: infinite loop --------------------------------------------------------

def test_T02_infinite_loop_is_timed_out_and_returns(tmp_path: Path) -> None:
    result = _run_local(tmp_path, "while True:\n    pass\n", timeout_s=2)
    assert result.state == "TIMED_OUT"
    assert result.timed_out is True
    assert result.duration_ms < 15_000


# -- T06: secrets in environment -----------------------------------------------

def test_T06_environment_contains_only_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-live-T06-should-not-appear"
    monkeypatch.setenv("DCE_VULTR_INFERENCE_KEY", secret)
    monkeypatch.setenv("DCE_SEED_PASSWORD", "seed-T06")
    script = "import os\nprint('\\n'.join(sorted(os.environ)))\n"
    result = _run_local(tmp_path, script)
    assert result.state == "COMPLETED", result.stderr
    assert secret not in result.stdout
    assert "seed-T06" not in result.stdout
    keys = {k for k in result.stdout.split() if k}
    dce_keys = {k for k in keys if k.startswith("DCE_")}
    assert dce_keys <= {"DCE_TASK_ID", "DCE_TIMEOUT_S"}


# -- T08: malformed script -----------------------------------------------------

def test_T08_syntax_error_is_failed_with_parser_error_and_no_artifacts(tmp_path: Path) -> None:
    script = "def broken(:\n    pass\n"
    result = _run_local(tmp_path, script)
    assert result.state == "FAILED_SANDBOX"
    assert "SyntaxError" in result.stderr
    assert result.artifacts == []


def test_T08_partial_output_is_not_exported_on_failure(tmp_path: Path) -> None:
    script = (
        "import json, pathlib\n"
        "pathlib.Path('out/summary.json').write_text(json.dumps({'a': 1}))\n"
        "raise RuntimeError('fail after writing')\n"
    )
    result = _run_local(tmp_path, script)
    assert result.state == "FAILED_SANDBOX"
    assert result.artifacts == []


# -- T09: execution timeout ----------------------------------------------------

def test_T09_sleep_past_timeout_is_timed_out(tmp_path: Path) -> None:
    # SDD uses sleep(60) with a 30 s limit. The same behaviour is checked here with shorter limits.
    result = _run_local(tmp_path, "import time\ntime.sleep(60)\n", timeout_s=2)
    assert result.state == "TIMED_OUT"
    assert result.artifacts == []


# -- Docker-only cases (SDD 9.8 T03, T04, T05, T07, T10, T11) ------------------------

def _docker_runner(tmp_path: Path) -> DockerSandboxRunner:
    image = os.environ.get("DCE_SANDBOX_IMAGE", "dce-worker:local")
    return DockerSandboxRunner(image=image, staging_root=tmp_path / "staging", timeout_s=30,
                               seccomp_path=DEFAULT_SECCOMP_PATH)


def _run_docker(tmp_path: Path, script: str, timeout_s: int = 30):
    runner = _docker_runner(tmp_path)
    task_id = str(uuid.uuid4())
    result = asyncio.run(runner.run(task_id, script, {}, timeout_s))
    return task_id, result


def _no_containers_left(task_id: str) -> bool:
    out = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=dce.task={task_id}"],
                         capture_output=True, text=True, check=False)
    return out.stdout.strip() == ""


@pytest.mark.docker
def test_T03_memory_exhaustion_is_oom_killed(tmp_path: Path) -> None:
    _, result = _run_docker(tmp_path, "x = bytearray(600 * 1024 * 1024)\nprint(len(x))\n")
    assert result.state == "FAILED_SANDBOX"
    assert result.oom_killed is True


@pytest.mark.docker
def test_T04_fork_bomb_is_blocked_by_pid_limit(tmp_path: Path) -> None:
    task_id, result = _run_docker(tmp_path, "import os\nwhile True:\n    os.fork()\n", timeout_s=15)
    assert result.state in {"FAILED_SANDBOX", "TIMED_OUT"}
    assert result.state != "COMPLETED"
    assert _no_containers_left(task_id)


@pytest.mark.docker
def test_T05_host_filesystem_is_not_visible(tmp_path: Path) -> None:
    script = (
        "import os\n"
        "for p in ('/home', '/root', '/var/lib/docker', '/etc/dce'):\n"
        "    print(p, os.path.exists(p))\n"
    )
    _, result = _run_docker(tmp_path, script)
    assert result.state == "COMPLETED", result.stderr
    assert "True" not in result.stdout


@pytest.mark.docker
def test_T07_outbound_network_fails(tmp_path: Path) -> None:
    script = (
        "import socket\n"
        "s = socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
    )
    _, result = _run_docker(tmp_path, script)
    assert result.state == "FAILED_SANDBOX"
    assert result.artifacts == []


@pytest.mark.docker
def test_T10_container_is_removed_after_run(tmp_path: Path) -> None:
    task_id, _ = _run_docker(tmp_path, "print('ok')\n")
    assert _no_containers_left(task_id)


@pytest.mark.docker
def test_T11_docker_api_socket_is_not_reachable(tmp_path: Path) -> None:
    script = (
        "import socket\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "s.connect('/var/run/docker.sock')\n"
    )
    _, result = _run_docker(tmp_path, script)
    assert result.state == "FAILED_SANDBOX"
    assert result.stderr


@pytest.mark.docker
def test_T12_host_health_after_hostile_task(tmp_path: Path) -> None:
    # Backend /api/health is checked on the VM (SDD 9.8 T12). Here: the runner is idle after the run.
    runner = _docker_runner(tmp_path)
    asyncio.run(runner.run(str(uuid.uuid4()), "while True:\n    pass\n", {}, 3))
    assert asyncio.run(runner.running_count()) == 0

