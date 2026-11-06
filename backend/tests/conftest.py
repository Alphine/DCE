"""Shared fixtures: a fresh app per test, seeded users, a fake sandbox runner, and a request helper."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.db import Db
from app.main import create_app
from app.sandbox.base import ArtifactFile, SandboxResult
from app.security import SESSION_COOKIE, hash_password
from app.util import new_id, utc_now

PASSWORD = "test-password-123!"
SEED_USERS = {"admin": "Admin", "analyst": "Analyst", "reviewer": "Reviewer",
              "approver": "Approver", "viewer": "Viewer"}

CSV_GOOD = (
    "district,water_depth_cm,road_status,affected_population,reported_at\n"
    "Kemang,35,blocked,120,2026-11-05T10:00:00Z\n"
    "Cilandak,,open,80,\n"
    "Menteng,12,open,,\n"
    "Kemang,45,blocked,200,\n"
    "Tebet,31,open,50,\n"
    "Tebet,10,open,0,\n"
).encode("utf-8")


@dataclass
class FakeRunner:
    """Stands in for the sandbox. Writes real output files under data_dir so validation runs for real."""

    data_dir: Path
    mode: str = "ok"          # ok | bad_json | missing_summary | sandbox_fail | hang
    name: str = "local"
    max_concurrent: int = 1
    calls: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    _release: asyncio.Event | None = None

    async def run(self, task_id: str, script: str, inputs: dict[str, bytes], timeout_s: int) -> SandboxResult:
        self.calls.append({"task_id": task_id, "script": script, "inputs": sorted(inputs), "timeout_s": timeout_s})
        if self.mode == "hang":
            self._release = asyncio.Event()
            await self._release.wait()
            return self._result(task_id, "FAILED_SANDBOX", exit_code=137, artifacts=[], stdout="", stderr="killed")
        if self.mode == "sandbox_fail":
            return self._result(task_id, "FAILED_SANDBOX", exit_code=1, artifacts=[], stdout="", stderr="boom")

        out = self.data_dir / "sandbox" / task_id
        out.mkdir(parents=True, exist_ok=True)
        files: dict[str, bytes] = {
            "summary.json": b'{"flooded_rows": 2}' if self.mode != "bad_json" else b"{not json",
            "situation_report.md": b"# Report\n\nSIMULATED_FACT\n",
        }
        if self.mode == "missing_summary":
            files.pop("summary.json")
        artifacts = []
        for name, data in files.items():
            path = out / name
            path.write_bytes(data)
            artifacts.append(ArtifactFile(name=name, path=str(path),
                                          sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
        return self._result(task_id, "COMPLETED", exit_code=0, artifacts=artifacts,
                            stdout="Profiling dataset...\nwrote summary.json", stderr="")

    def _result(self, task_id: str, state: str, *, exit_code: int | None, artifacts: list[ArtifactFile],
                stdout: str, stderr: str) -> SandboxResult:
        return SandboxResult(
            task_id=task_id, state=state, runner=self.name, exit_code=exit_code, duration_ms=12,
            timed_out=False, oom_killed=False, container_id=None, stdout=stdout, stderr=stderr,
            stdout_truncated=False, stderr_truncated=False, code_sha256="", artifacts=artifacts,
        )

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)
        if self._release is not None:
            self._release.set()

    async def sweep_orphans(self) -> int:
        return 0

    async def running_count(self) -> int:
        return 0


class Api:
    """Sends requests with an explicit Cookie header so the shared client never mixes sessions."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __call__(self, method: str, url: str, token: str | None = None, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})
        if token:
            headers["Cookie"] = f"{SESSION_COOKIE}={token}"
        return self.client.request(method, url, headers=headers, **kwargs)


class Env:
    def __init__(self, app: FastAPI, client: TestClient, settings: Settings, runner: FakeRunner) -> None:
        self.app = app
        self.client = client
        self.api = Api(client)
        self.settings = settings
        self.runner = runner
        self.db: Db = app.state.db
        self.tokens: dict[str, str] = {}

    def login(self, username: str, password: str = PASSWORD) -> str:
        response = self.api("POST", "/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        token = response.cookies[SESSION_COOKIE]
        self.client.cookies.clear()
        self.tokens[username] = token
        return token

    def token(self, username: str) -> str:
        if username not in self.tokens:
            self.login(username)
        return self.tokens[username]

    def wait_state(self, task_id: str, states: set[str], as_user: str = "reviewer", timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            last = self.api("GET", f"/api/agent/tasks/{task_id}", self.token(as_user)).json()
            if last["state"] in states:
                return last
            time.sleep(0.05)
        raise AssertionError(f"task stuck in {last.get('state')}, wanted {states}")

    def upload(self, username: str, data: bytes = CSV_GOOD, filename: str = "flood_incidents.csv",
               name: str | None = None) -> httpx.Response:
        form = {"name": name} if name else {}
        return self.api("POST", "/api/datasets", self.token(username),
                        files={"file": (filename, data, "text/csv")}, data=form)

    def approved_dataset(self, uploader: str = "analyst", approver: str = "reviewer") -> str:
        dataset_id = self.upload(uploader).json()["id"]
        response = self.api("POST", f"/api/datasets/{dataset_id}/approve", self.token(approver))
        assert response.status_code == 200, response.text
        return dataset_id

    def create_task(self, username: str = "analyst", dataset_id: str | None = None) -> str:
        response = self.api("POST", "/api/agent/tasks", self.token(username), json={
            "instruction": "Analyze this flood incident dataset and count flooded districts.",
            "dataset_id": dataset_id or self.approved_dataset(),
            "requested_outputs": ["affected_areas", "blocked_roads", "situation_report"],
        })
        assert response.status_code == 202, response.text
        return response.json()["task_id"]

    def audit_rows(self) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY id").fetchall()
            return [dict(r) | {"detail": json.loads(r["detail_json"])} for r in rows]


def seed_users(db: Db) -> None:
    password_hash = hash_password(PASSWORD)
    with db.transaction() as conn:
        for username, role in SEED_USERS.items():
            user_id = new_id()
            conn.execute("INSERT INTO users (id, username, password_hash, status, created_at) "
                         "VALUES (?, ?, ?, 'active', ?)", (user_id, username, password_hash, utc_now()))
            conn.execute("INSERT INTO user_roles (user_id, role) VALUES (?, ?)", (user_id, role))


def build_settings(tmp_path: Path, **overrides: Any) -> Settings:
    data_dir = tmp_path / "data"
    values: dict[str, Any] = {
        "_env_file": None,
        "env": "development",
        "data_dir": data_dir,
        "database_path": data_dir / "dce.sqlite3",
        "frontend_dir": tmp_path / "no-frontend",
        "serve_frontend": False,
        "sandbox_runner": "local",
        "seed_password": SecretStr(PASSWORD),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[Callable[..., Env]]:
    clients: list[TestClient] = []

    def _make(*, runner_mode: str = "ok", inference: Any = None, min_interval_s: float = 0.0,
              seed: bool = True, settings: Settings | None = None, **overrides: Any) -> Env:
        cfg = settings or build_settings(tmp_path, **overrides)
        runner = FakeRunner(data_dir=cfg.data_dir, mode=runner_mode)
        app = create_app(cfg, runner=runner, inference=inference, min_agent_interval_s=min_interval_s)
        client = TestClient(app, base_url="http://testserver")
        client.__enter__()
        clients.append(client)
        if seed:
            seed_users(app.state.db)
        return Env(app, client, cfg, runner)

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def env(make_env: Callable[..., Env]) -> Env:
    return make_env()


@pytest.fixture
def logged_in(env: Env) -> Env:
    for username in SEED_USERS:
        env.login(username)
    return env
