"""LocalProcessRunner (development only): normal run, timeout, output rules, refusal in production."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest

from app.sandbox.errors import SandboxConfigError, SandboxInputError
from app.sandbox.local_runner import LocalProcessRunner

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _runner(tmp_path: Path, **kw: object) -> LocalProcessRunner:
    opts: dict[str, object] = dict(env="development", staging_root=tmp_path / "staging", timeout_s=10)
    opts.update(kw)
    return LocalProcessRunner(**opts)  # type: ignore[arg-type]


def _run(runner: LocalProcessRunner, script: str, timeout_s: int = 10, inputs: dict[str, bytes] | None = None):
    task_id = str(uuid.uuid4())
    return task_id, asyncio.run(runner.run(task_id, script, inputs or {}, timeout_s))


def test_refuses_to_construct_in_production(tmp_path: Path) -> None:
    with pytest.raises(SandboxConfigError, match="production"):
        LocalProcessRunner(env="production", staging_root=tmp_path)


def test_every_result_is_marked_local_with_no_container(tmp_path: Path) -> None:
    _, result = _run(_runner(tmp_path), "print('hi')")
    assert result.runner == "local"
    assert result.container_id is None
    assert result.oom_killed is False


def test_normal_run_stages_allowlisted_output_with_hash(tmp_path: Path) -> None:
    script = (
        "import json, pathlib\n"
        "print('profiling')\n"
        "pathlib.Path('out/summary.json').write_text(json.dumps({'flooded': 3}))\n"
        "pathlib.Path('out/chart.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\n' + b'0' * 16)\n"
    )
    task_id, result = _run(_runner(tmp_path), script)
    assert result.state == "COMPLETED", result.stderr
    assert result.exit_code == 0
    assert "profiling" in result.stdout
    names = sorted(a.name for a in result.artifacts)
    assert names == ["chart.png", "summary.json"]
    for art in result.artifacts:
        data = Path(art.path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == art.sha256
        assert art.size_bytes == len(data)
        assert Path(art.path).is_relative_to(tmp_path / "staging" / task_id)
    assert result.code_sha256 == hashlib.sha256(script.encode()).hexdigest()


def test_inputs_are_visible_in_workspace(tmp_path: Path) -> None:
    script = "print(open('flood.csv', encoding='utf-8').read().splitlines()[0])"
    _, result = _run(_runner(tmp_path), script, inputs={"flood.csv": b"district,depth\nKemang,35\n"})
    assert result.state == "COMPLETED", result.stderr
    assert "district,depth" in result.stdout


def test_timeout_marks_timed_out(tmp_path: Path) -> None:
    _, result = _run(_runner(tmp_path), "while True:\n    pass\n", timeout_s=2)
    assert result.state == "TIMED_OUT"
    assert result.timed_out is True
    assert result.artifacts == []


def test_nonzero_exit_is_failed_sandbox(tmp_path: Path) -> None:
    _, result = _run(_runner(tmp_path), "raise SystemExit(3)")
    assert result.state == "FAILED_SANDBOX"
    assert result.exit_code == 3


def test_output_is_truncated_to_64_kb_with_flag(tmp_path: Path) -> None:
    _, result = _run(_runner(tmp_path), "print('x' * (200 * 1024))")
    assert result.state == "COMPLETED"
    assert len(result.stdout.encode("utf-8")) <= 64 * 1024
    assert result.stdout_truncated is True


def test_disallowed_output_name_yields_no_artifacts(tmp_path: Path) -> None:
    script = "import pathlib\npathlib.Path('out/evil.sh').write_text('rm -rf /')\n"
    _, result = _run(_runner(tmp_path), script)
    assert result.state == "FAILED_SANDBOX"
    assert result.artifacts == []


def test_bad_magic_bytes_yield_no_partial_export(tmp_path: Path) -> None:
    script = (
        "import json, pathlib\n"
        "pathlib.Path('out/summary.json').write_text(json.dumps({'ok': 1}))\n"
        "pathlib.Path('out/chart.png').write_bytes(b'GIF89a not really')\n"
    )
    _, result = _run(_runner(tmp_path), script)
    assert result.state == "FAILED_SANDBOX"
    assert result.artifacts == []
    assert not (tmp_path / "staging").exists() or not any((tmp_path / "staging").rglob("*.json"))


def test_subdirectory_in_out_is_rejected(tmp_path: Path) -> None:
    script = "import pathlib\npathlib.Path('out/nested').mkdir()\n"
    _, result = _run(_runner(tmp_path), script)
    assert result.state == "FAILED_SANDBOX"
    assert result.artifacts == []


def test_task_timeout_is_capped_by_hard_limit(tmp_path: Path) -> None:
    runner = _runner(tmp_path, timeout_s=2)
    _, result = _run(runner, "import time\ntime.sleep(30)\n", timeout_s=600)
    assert result.state == "TIMED_OUT"
    assert result.duration_ms < 20_000


def test_invalid_script_size_is_rejected_before_running(tmp_path: Path) -> None:
    with pytest.raises(SandboxInputError):
        _run(_runner(tmp_path), "#" * (64 * 1024 + 1))


def test_inputs_with_unsafe_name_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(SandboxInputError):
        _run(_runner(tmp_path), "pass", inputs={"../evil.csv": b"x"})


def test_child_environment_is_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-test-DO-NOT-LEAK-12345"
    monkeypatch.setenv("DCE_VULTR_INFERENCE_KEY", secret)
    monkeypatch.setenv("DCE_DATABASE_PATH", "/secret/dce.sqlite3")
    script = "import os, json\nprint(json.dumps(sorted(os.environ)))\n"
    _, result = _run(_runner(tmp_path), script)
    assert result.state == "COMPLETED", result.stderr
    assert secret not in result.stdout
    assert "DCE_DATABASE_PATH" not in result.stdout
    assert "DCE_VULTR_INFERENCE_KEY" not in result.stdout
    assert "DCE_TASK_ID" in result.stdout
