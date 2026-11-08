"""Planner repair: one retry after a schema failure, with field names only in the feedback."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest

from app.agent.inference_client import MockInference, PlanRequest
from app.agent.planner import Planner, PlanningFailed
from app.config import Settings
from app.agent.schemas import PlanError, validate_plan

CEILING = {"timeout_s": 30, "memory_mb": 512, "pids": 64}


def _valid_plan() -> dict[str, Any]:
    request = PlanRequest(instruction="x", requested_outputs=[], dataset_name="d", profile={}, limits=dict(CEILING))
    return asyncio.run(MockInference().plan(request))


class ScriptedClient:
    """Returns the scripted outputs in order and records every request it received."""

    model_id = "scripted"

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.requests: list[PlanRequest] = []

    async def plan(self, request: PlanRequest) -> Any:
        self.requests.append(request)
        return self.outputs.pop(0)


def _planner(tmp_path: Path, client: ScriptedClient) -> Planner:
    return Planner(Settings(_env_file=None, data_dir=tmp_path), client)  # type: ignore[arg-type]


def _run(planner: Planner) -> Any:
    return asyncio.run(planner.create_plan(instruction="analyse", requested_outputs=["summary.json"],
                                           dataset_name="flood", profile={"columns": []}))


def test_schema_failure_is_repaired_on_the_second_attempt(tmp_path: Path) -> None:
    broken = copy.deepcopy(_valid_plan())
    del broken["data_class"]
    client = ScriptedClient([broken, _valid_plan()])
    plan = _run(_planner(tmp_path, client))
    assert plan.data_class == "SIMULATED_FACT"
    assert len(client.requests) == 2
    assert client.requests[0].feedback is None
    assert "data_class" in (client.requests[1].feedback or "")


def test_feedback_contains_field_names_and_never_values(tmp_path: Path) -> None:
    broken = copy.deepcopy(_valid_plan())
    broken["data_class"] = "SECRET-VALUE-XYZ"
    client = ScriptedClient([broken, _valid_plan()])
    _run(_planner(tmp_path, client))
    feedback = client.requests[1].feedback or ""
    assert "data_class" in feedback
    assert "SECRET-VALUE-XYZ" not in feedback


def test_two_schema_failures_stop_with_the_schema_code(tmp_path: Path) -> None:
    broken = copy.deepcopy(_valid_plan())
    del broken["data_class"]
    client = ScriptedClient([broken, broken])
    with pytest.raises(PlanningFailed) as info:
        _run(_planner(tmp_path, client))
    assert info.value.code == "PLAN_INVALID_SCHEMA"
    assert len(client.requests) == 2


def test_policy_refusals_are_not_retried(tmp_path: Path) -> None:
    bad = copy.deepcopy(_valid_plan())
    bad["tools"][0] = "shell_exec"
    bad["steps"][0]["tool"] = "shell_exec"
    client = ScriptedClient([bad, _valid_plan()])
    with pytest.raises(PlanningFailed) as info:
        _run(_planner(tmp_path, client))
    assert info.value.code == "PLAN_UNKNOWN_TOOL"
    assert len(client.requests) == 1


def test_error_message_lists_paths_for_a_nested_failure() -> None:
    broken = copy.deepcopy(_valid_plan())
    broken["steps"][0].pop("id", None)
    with pytest.raises(PlanError) as info:
        validate_plan(broken, CEILING)
    assert info.value.code == "PLAN_INVALID_SCHEMA"
    assert "steps.0.id" in info.value.message
