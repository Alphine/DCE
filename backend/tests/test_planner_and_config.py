"""Configuration rules, strict plan validation, generated-code checks, and the mock task script."""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent.inference_client import InferenceError, MockInference, PlanRequest, check_script
from app.agent.planner import Planner, PlanningFailed
from app.agent.schemas import PlanError, validate_plan
from app.config import Settings

CEILING = {"timeout_s": 30, "memory_mb": 512, "pids": 64}


def _mock_plan() -> dict:
    request = PlanRequest(instruction="x", requested_outputs=[], dataset_name="d", profile={}, limits=dict(CEILING))
    return asyncio.run(MockInference().plan(request))


def test_production_refuses_local_runner(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="refused when DCE_ENV=production"):
        Settings(_env_file=None, env="production", sandbox_runner="local", data_dir=tmp_path)


def test_production_allows_docker_and_disables_frontend_by_default(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, env="production", sandbox_runner="docker", data_dir=tmp_path)
    assert cfg.frontend_enabled is False
    assert Settings(_env_file=None, data_dir=tmp_path).frontend_enabled is True


def test_vultr_mode_needs_key_and_model(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, inference_mode="vultr", data_dir=tmp_path)


def test_secrets_are_masked_in_repr(tmp_path: Path) -> None:
    from pydantic import SecretStr

    cfg = Settings(_env_file=None, inference_mode="vultr", inference_model="m1",
                   vultr_inference_key=SecretStr("sk-test-secret"), data_dir=tmp_path)
    assert "sk-test-secret" not in repr(cfg)


def test_mock_plan_is_valid() -> None:
    plan = validate_plan(_mock_plan(), CEILING)
    assert plan.expected_outputs == ["summary.json", "situation_report.md"]
    assert plan.data_class == "SIMULATED_FACT"


def test_unknown_tool_is_refused() -> None:
    raw = _mock_plan()
    raw["tools"][0] = "shell_exec"
    raw["steps"][0]["tool"] = "shell_exec"
    with pytest.raises(PlanError) as exc:
        validate_plan(raw, CEILING)
    assert exc.value.code == "PLAN_UNKNOWN_TOOL"


def test_extra_fields_are_rejected() -> None:
    raw = _mock_plan()
    raw["run_as_root"] = True
    with pytest.raises(PlanError) as exc:
        validate_plan(raw, CEILING)
    assert exc.value.code == "PLAN_INVALID_SCHEMA"


def test_limits_may_be_lowered_but_not_raised() -> None:
    lowered = _mock_plan()
    lowered["limits"]["timeout_s"] = 10
    assert validate_plan(lowered, CEILING).limits.timeout_s == 10

    raised = _mock_plan()
    raised["limits"]["memory_mb"] = 1024
    with pytest.raises(PlanError) as exc:
        validate_plan(raised, CEILING)
    assert exc.value.code == "PLAN_LIMIT_RAISED"


def test_expected_output_must_be_produced_by_a_planned_tool() -> None:
    raw = _mock_plan()
    raw["expected_outputs"] = ["summary.json", "situation_report.md", "chart.png", "secrets.txt"]
    with pytest.raises(PlanError) as exc:
        validate_plan(raw, CEILING)
    assert exc.value.code in {"PLAN_OUTPUT_UNPRODUCED", "PLAN_INVALID_SCHEMA"}


def test_required_output_must_be_expected() -> None:
    raw = copy.deepcopy(_mock_plan())
    raw["expected_outputs"] = ["summary.json"]
    with pytest.raises(PlanError) as exc:
        validate_plan(raw, CEILING)
    assert exc.value.code == "PLAN_OUTPUT_UNPRODUCED"


def test_non_object_plan_is_refused() -> None:
    with pytest.raises(PlanError):
        validate_plan(["not", "a", "dict"], CEILING)


def test_planner_maps_inference_errors_to_reason_codes(tmp_path: Path) -> None:
    class BrokenClient:
        model_id = "broken"

        async def plan(self, request: PlanRequest) -> dict:
            raise InferenceError("INFERENCE_TIMEOUT", "timed out")

        async def generate_code(self, plan: dict, profile: dict) -> str:
            return ""

    cfg = Settings(_env_file=None, data_dir=tmp_path)
    planner = Planner(cfg, BrokenClient())  # type: ignore[arg-type]
    with pytest.raises(PlanningFailed) as exc:
        asyncio.run(planner.create_plan(instruction="x", requested_outputs=[], dataset_name="d", profile={}))
    assert exc.value.code == "INFERENCE_TIMEOUT"


def test_script_checks_block_network_and_dynamic_execution() -> None:
    assert check_script("import csv\nprint('ok')\n") is None
    for bad in ("import socket\n", "import subprocess\n", "import os\nos.system('id')\n",
                "eval('1')\n", "from urllib import request\n", "def broken(:\n"):
        with pytest.raises(InferenceError):
            check_script(bad)


def test_mock_script_passes_its_own_checks() -> None:
    script = asyncio.run(MockInference().generate_code(_mock_plan(), {}))
    check_script(script)


def test_mock_script_treats_nulls_as_unknown(tmp_path: Path) -> None:
    script = asyncio.run(MockInference().generate_code(_mock_plan(), {}))
    (tmp_path / "task.py").write_text(script, encoding="utf-8")
    (tmp_path / "dataset.csv").write_text(
        "district,water_depth_cm,road_status,affected_population\n"
        "Kemang,35,blocked,120\n"
        "Cilandak,,open,80\n"
        "Menteng,12,open,\n"
        "Kemang,45,blocked,200\n"
        "Tebet,31,open,50\n"
        "Tebet,10,open,0\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, "-I", "task.py"], cwd=tmp_path, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert set(summary) == {"dataset_rows", "flooded_districts", "blocked_roads", "affected_population", "data_class"}
    assert summary["dataset_rows"] == 6
    assert summary["flooded_districts"] == [
        {"district": "Cilandak", "incidents": 1, "flooded_incidents": 0},
        {"district": "Kemang", "incidents": 2, "flooded_incidents": 2},
        {"district": "Menteng", "incidents": 1, "flooded_incidents": 0},
        {"district": "Tebet", "incidents": 2, "flooded_incidents": 1},
    ]
    assert summary["blocked_roads"] == 2
    assert summary["affected_population"] == {"sum": 450.0, "unknown_rows": 1}
    assert summary["data_class"] == "SIMULATED_FACT"
    report = (tmp_path / "out" / "situation_report.md").read_text(encoding="utf-8")
    assert "SIMULATED_FACT" in report
