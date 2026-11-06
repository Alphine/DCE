"""Seed script behaviour and the dashboard summary contract."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable

from tests.conftest import PASSWORD, Env

BACKEND = Path(__file__).resolve().parents[1]


def _seed_env(tmp_path: Path, password: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DCE_")}
    env["DCE_DATA_DIR"] = str(tmp_path / "seed-data")
    env["DCE_DATABASE_PATH"] = str(tmp_path / "seed-data" / "dce.sqlite3")
    env["DCE_SANDBOX_RUNNER"] = "local"
    if password is not None:
        env["DCE_SEED_PASSWORD"] = password
    return env


def _run_seed(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "app.seed"], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=120)


def test_seed_refuses_without_password(tmp_path: Path) -> None:
    result = _run_seed(_seed_env(tmp_path, None))
    assert result.returncode == 2
    assert "DCE_SEED_PASSWORD" in result.stderr


def test_seed_is_idempotent_and_never_prints_password(tmp_path: Path) -> None:
    secret = "seed-password-long-enough"
    env = _seed_env(tmp_path, secret)
    first = _run_seed(env)
    assert first.returncode == 0, first.stderr
    second = _run_seed(env)
    assert second.returncode == 0, second.stderr
    assert "exists" in second.stdout
    assert secret not in first.stdout + first.stderr
    conn = sqlite3.connect(tmp_path / "seed-data" / "dce.sqlite3")
    try:
        names = sorted(r[0] for r in conn.execute("SELECT username FROM users"))
        roles = {r[0]: r[1] for r in conn.execute(
            "SELECT u.username, r.role FROM users u JOIN user_roles r ON r.user_id = u.id")}
    finally:
        conn.close()
    assert names == ["admin", "analyst", "approver", "reviewer"]
    assert roles["approver"] == "Approver"


def test_dashboard_summary_shape(logged_in: Env) -> None:
    response = logged_in.api("GET", "/api/dashboard/summary", logged_in.token("viewer"))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"datasets", "tasks", "artifacts", "sandbox", "inference", "quota", "env"}
    assert body["inference"] == {"mode": "mock", "model": "mock-planner"}
    assert body["sandbox"]["runner"] == "local"
    assert body["sandbox"]["max_concurrent"] == 1
    assert body["quota"]["limit"] == 20
    assert body["env"] == "development"


def test_frontend_mount_is_optional(make_env: Callable[..., Env]) -> None:
    env = make_env()
    assert env.api("GET", "/api/health").status_code == 200
    assert PASSWORD
