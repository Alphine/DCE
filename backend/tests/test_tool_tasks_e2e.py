"""End-to-end agent tasks for the registry tools through the test client.

The planner is a test-only inference client that routes to the tool-aware mock (mock_script.py). The default
MockInference and the default flood flow are not changed. Scripts run for real in LocalProcessRunner
(development only, not isolated), so each test executes the generated task.py as a subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from app.agent.mock_script import build_tool_script, mock_tool_plan
from app.rules import engine
from app.sandbox.local_runner import LocalProcessRunner
from tests.conftest import Env
from tests.test_dataset_reject_geojson import GEO_OK

RICH_CSV = (
    "district,water_depth_cm,road_status,affected_population\n"
    "Kemang,120,blocked,10\n"
    "Kemang,50,open,20\n"
    "=Tebet,49.9,blocked,5\n"
    "Menteng,,closed,\n"
    "Cilandak,100,open,3\n"
    "Pasar Minggu,nan,blocked,1\n"
).encode("utf-8")


class ToolMockInference:
    """Test-only planner: returns the tool-aware mock plan and script for the given registry tools."""

    model_id = "mock-tools"

    def __init__(self, tools: list[str], *, want_pdf: bool = False) -> None:
        self.tools = list(tools)
        self.want_pdf = want_pdf

    async def plan(self, request: Any) -> dict[str, Any]:
        return mock_tool_plan(self.tools, request.limits, want_pdf=self.want_pdf)

    async def generate_code(self, plan: dict[str, Any], profile: dict[str, Any]) -> str:
        return build_tool_script(plan["tools"], want_pdf="situation_report.pdf" in plan["expected_outputs"])


def _use_real_runner(env: Env) -> None:
    env.app.state.services.manager.runner = LocalProcessRunner(
        env="development", staging_root=env.settings.data_dir / "sandbox_staging", timeout_s=30)


def _approved(env: Env, data: bytes, filename: str) -> str:
    dataset_id = env.upload("analyst", data=data, filename=filename).json()["id"]
    response = env.api("POST", f"/api/datasets/{dataset_id}/approve", env.token("reviewer"))
    assert response.status_code == 200, response.text
    return dataset_id


def _start_task(env: Env, dataset_id: str) -> str:
    response = env.api("POST", "/api/agent/tasks", env.token("analyst"), json={
        "instruction": "Analyse the approved dataset with the registry tools.",
        "dataset_id": dataset_id,
        "requested_outputs": ["situation_report"],
    })
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    env.wait_state(task_id, {"AWAITING_APPROVAL", "FAILED_PLANNING"}, as_user="analyst", timeout=30)
    return task_id


def _run_to_review(env: Env, dataset_id: str) -> dict[str, Any]:
    task_id = _start_task(env, dataset_id)
    waiting = env.wait_state(task_id, {"AWAITING_APPROVAL", "FAILED_PLANNING"}, as_user="analyst", timeout=30)
    if waiting["state"] == "FAILED_PLANNING":
        return waiting
    gate_a = env.api("POST", f"/api/agent/tasks/{task_id}/approve", env.token("approver"),
                     json={"gate": "A", "decision": "approve", "note": "plan ok"})
    assert gate_a.status_code == 200, gate_a.text
    return env.wait_state(task_id, {"AWAITING_REVIEW", "FAILED_SANDBOX", "REJECTED_OUTPUT", "FAILED_PLANNING"},
                          as_user="analyst", timeout=60)


def _download(env: Env, artifact_id: str) -> Any:
    response = env.api("GET", f"/api/artifacts/{artifact_id}", env.token("analyst"))
    assert response.status_code == 200, response.text
    return response


def _artifacts(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in task["artifacts"]}


@pytest.fixture
def tool_env(make_env: Callable[..., Env]) -> Callable[..., Env]:
    def _make(tools: list[str], *, want_pdf: bool = False, real_runner: bool = True) -> Env:
        env = make_env(inference=ToolMockInference(tools, want_pdf=want_pdf))
        for username in ("analyst", "reviewer", "approver"):
            env.login(username)
        if real_runner:
            _use_real_runner(env)
        return env
    return _make


def test_geojson_analyzer_and_pdf_report_run_end_to_end(tool_env: Callable[..., Env]) -> None:
    env = tool_env(["geojson_analyzer", "report_generator"], want_pdf=True)
    dataset_id = _approved(env, GEO_OK, "zones.geojson")
    task = _run_to_review(env, dataset_id)
    assert task["state"] == "AWAITING_REVIEW", task.get("error_reason")
    assert task["sandbox"]["runner"] == "local"

    done = env.api("POST", f"/api/agent/tasks/{task['id']}/approve", env.token("reviewer"),
                   json={"gate": "B", "decision": "approve"})
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "COMPLETED"

    artifacts = _artifacts(env.api("GET", f"/api/agent/tasks/{task['id']}", env.token("analyst")).json())
    assert set(artifacts) == {"summary.json", "situation_report.md", "situation_report.pdf"}

    summary = json.loads(_download(env, artifacts["summary.json"]["id"]).content)
    assert summary["feature_count"] == 4
    assert summary["geometry_types"] == {"LineString": 1, "Point": 1, "Polygon": 1, "null": 1}

    pdf = _download(env, artifacts["situation_report.pdf"]["id"])
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["x-content-type-options"] == "nosniff"


def test_hazard_resource_blocked_roads_and_pdf_run_end_to_end(tool_env: Callable[..., Env]) -> None:
    tools = ["hazard_analyzer", "resource_estimator", "blocked_roads", "report_generator"]
    env = tool_env(tools, want_pdf=True)
    dataset_id = _approved(env, RICH_CSV, "rich_flood.csv")
    task = _run_to_review(env, dataset_id)
    assert task["state"] == "AWAITING_REVIEW", task.get("error_reason")
    assert env.api("POST", f"/api/agent/tasks/{task['id']}/approve", env.token("reviewer"),
                   json={"gate": "B", "decision": "approve"}).json()["state"] == "COMPLETED"

    artifacts = _artifacts(env.api("GET", f"/api/agent/tasks/{task['id']}", env.token("analyst")).json())
    assert set(artifacts) == {"hazard_results.json", "resource_estimate.json", "blocked_roads.csv",
                              "situation_report.md", "situation_report.pdf"}

    pack = engine.load_default_pack()[1]
    hazard = json.loads(_download(env, artifacts["hazard_results.json"]["id"]).content)
    assert hazard["data_class"] == "INFERRED_FACT"
    assert hazard["rule_pack"]["sha256"] == pack["pack_sha256"]
    assert hazard["road_blocked_candidates"] == 3
    assert hazard["counts_by_severity"] == {"HIGH": 2, "LOW": 1, "MEDIUM": 1, "UNKNOWN": 2}

    resource = json.loads(_download(env, artifacts["resource_estimate.json"]["id"]).content)
    assert resource["data_class"] == "SIMULATED_FACT"
    assert resource["inputs"]["affected_rows"] == 3

    blocked = _download(env, artifacts["blocked_roads.csv"]["id"]).content.decode("utf-8").splitlines()
    assert blocked[0] == "row,district,road_status,water_depth_cm"
    assert len(blocked) == 5
    assert any(line.startswith("3,'=Tebet,blocked,") for line in blocked)

    assert _download(env, artifacts["situation_report.pdf"]["id"]).content.startswith(b"%PDF")


def test_planning_refuses_a_tool_that_does_not_accept_the_dataset_kind(tool_env: Callable[..., Env]) -> None:
    env = tool_env(["geojson_analyzer", "report_generator"], want_pdf=False)
    dataset_id = _approved(env, RICH_CSV, "rich_flood.csv")
    task = _run_to_review(env, dataset_id)
    assert task["state"] == "FAILED_PLANNING"
    assert task["error_reason"] == "PLAN_INPUT_KIND_MISMATCH"


def test_tampered_rule_pack_refuses_to_run(make_env: Callable[..., Env], tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    tampered = tmp_path / "flood_tampered.json"
    tampered.write_bytes(engine.DEFAULT_PACK_PATH.read_bytes().replace(b'"water_depth_cm_gte": 100',
                                                                       b'"water_depth_cm_gte": 1'))
    monkeypatch.setattr(engine, "DEFAULT_PACK_PATH", tampered)
    env = make_env(inference=ToolMockInference(["hazard_analyzer", "report_generator"]))
    for username in ("analyst", "reviewer", "approver"):
        env.login(username)
    dataset_id = env.approved_dataset()
    task = _run_to_review(env, dataset_id)
    assert task["state"] == "FAILED_SANDBOX"
    assert task["error_reason"] == "RULE_PACK_INTEGRITY"
    assert env.runner.calls == [], "no sandbox run may start with a tampered rule pack"
