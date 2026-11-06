"""make_runner selects the runner from settings, and the local runner refuses production."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sandbox.docker_runner import DockerSandboxRunner
from app.sandbox.errors import SandboxConfigError
from app.sandbox.factory import make_runner
from app.sandbox.local_runner import LocalProcessRunner


def _settings(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base = dict(
        env="development",
        data_dir=tmp_path,
        sandbox_runner="local",
        sandbox_image="dce-worker:local",
        sandbox_max_concurrent=1,
        sandbox_timeout_s=30,
        sandbox_memory_mb=512,
        sandbox_pids=64,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_local_runner_selected_in_development(tmp_path: Path) -> None:
    runner = make_runner(_settings(tmp_path, sandbox_runner="local"))
    assert isinstance(runner, LocalProcessRunner)
    assert runner.name == "local"
    assert runner.max_concurrent == 1


def test_docker_runner_selected(tmp_path: Path) -> None:
    runner = make_runner(_settings(tmp_path, sandbox_runner="docker", sandbox_max_concurrent=2))
    assert isinstance(runner, DockerSandboxRunner)
    assert runner.name == "docker"
    assert runner.max_concurrent == 2


def test_runner_name_is_case_and_space_tolerant(tmp_path: Path) -> None:
    runner = make_runner(_settings(tmp_path, sandbox_runner=" Docker "))
    assert isinstance(runner, DockerSandboxRunner)


def test_unknown_runner_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(SandboxConfigError, match="unknown DCE_SANDBOX_RUNNER"):
        make_runner(_settings(tmp_path, sandbox_runner="firecracker"))


def test_local_runner_refused_in_production(tmp_path: Path) -> None:
    with pytest.raises(SandboxConfigError, match="production"):
        make_runner(_settings(tmp_path, env="production", sandbox_runner="local"))


def test_docker_runner_allowed_in_production(tmp_path: Path) -> None:
    runner = make_runner(_settings(tmp_path, env="production", sandbox_runner="docker"))
    assert runner.name == "docker"


def test_staging_root_is_under_data_dir(tmp_path: Path) -> None:
    runner = make_runner(_settings(tmp_path, sandbox_runner="local"))
    assert isinstance(runner, LocalProcessRunner)
    assert runner._staging_root == tmp_path / "sandbox_staging"  # noqa: SLF001
