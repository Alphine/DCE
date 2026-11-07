"""Registry schemas, rule pack integrity, hazard and resource determinism, script parity, and PDF output."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.agent import outputs as outputs_mod
from app.agent.inference_client import MockInference, PlanRequest, check_script
from app.agent.mock_script import build_tool_script, mock_tool_plan
from app.agent.outputs import OutputRejected, validate_outputs
from app.agent.schemas import PlanError, validate_plan
from app.agent.tools import DATASET_INPUT_NAMES, TOOL_REGISTRY, inputs_for_tools
from app.datasets import MAX_UPLOAD_BYTES
from app.rules import engine
from app.rules.engine import RulePackError, evaluate_hazards, estimate_resources, parse_pack
from app.sandbox.base import ArtifactFile
from app.sandbox.security import ARTIFACT_RULES, check_artifact

CEILING = {"timeout_s": 30, "memory_mb": 512, "pids": 64}
NEW_TOOLS = ["geojson_analyzer", "hazard_analyzer", "resource_estimator", "blocked_roads", "report_generator"]

RICH_CSV = (
    "district,water_depth_cm,road_status,affected_population\n"
    "Kemang,120,blocked,10\n"
    "Kemang,50,open,20\n"
    "=Tebet,49.9,blocked,5\n"
    "Menteng,,closed,\n"
    "Cilandak,100,open,3\n"
    "Pasar Minggu,nan,blocked,1\n"
).encode("utf-8")


def _run_script(workdir: Path, script: str, inputs: dict[str, bytes]) -> subprocess.CompletedProcess:
    workdir.mkdir(parents=True, exist_ok=True)
    for name, data in inputs.items():
        (workdir / name).write_bytes(data)
    (workdir / "task.py").write_text(script, encoding="utf-8")
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "win32" and "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return subprocess.run([sys.executable, "-I", "task.py"], cwd=str(workdir), env=env,
                          capture_output=True, timeout=60)


def _pack() -> dict[str, Any]:
    _, pack = engine.load_default_pack()
    return pack


# ----- registry -----------------------------------------------------------------------------------------

def test_registry_entries_are_complete() -> None:
    for name, spec in TOOL_REGISTRY.items():
        assert spec.name == name
        assert spec.input_kinds and set(spec.input_kinds) <= {"CSV", "GEOJSON"}, name
        assert set(spec.outputs) <= set(outputs_mod.OUTPUT_RULES), name
        assert set(spec.outputs) <= set(ARTIFACT_RULES), name
        assert set(spec.required_outputs) <= set(spec.outputs), name
        assert set(spec.output_schema) == set(spec.outputs), name
        assert spec.data_class in {"SIMULATED_FACT", "INFERRED_FACT"}, name


def test_new_tools_have_expected_contracts() -> None:
    assert TOOL_REGISTRY["geojson_analyzer"].input_kinds == ("GEOJSON",)
    assert TOOL_REGISTRY["geojson_analyzer"].outputs == ("summary.json",)
    assert TOOL_REGISTRY["hazard_analyzer"].data_class == "INFERRED_FACT"
    assert TOOL_REGISTRY["hazard_analyzer"].outputs == ("hazard_results.json",)
    assert TOOL_REGISTRY["resource_estimator"].data_class == "SIMULATED_FACT"
    assert TOOL_REGISTRY["blocked_roads"].outputs == ("blocked_roads.csv",)
    assert "situation_report.pdf" in TOOL_REGISTRY["report_generator"].outputs
    assert "situation_report.pdf" not in TOOL_REGISTRY["report_generator"].required_outputs
    assert inputs_for_tools(["hazard_analyzer", "resource_estimator"]) == ("rule_pack.json",)
    assert inputs_for_tools(["csv_analyzer"]) == ()
    assert DATASET_INPUT_NAMES == {"CSV": "dataset.csv", "GEOJSON": "dataset.geojson"}


def test_default_mock_plan_is_unchanged() -> None:
    request = PlanRequest(instruction="x", requested_outputs=[], dataset_name="d", profile={}, limits=dict(CEILING))
    import asyncio
    plan = asyncio.run(MockInference().plan(request))
    assert plan["tools"] == ["csv_analyzer", "chart_generator", "report_generator"]
    assert plan["expected_outputs"] == ["summary.json", "situation_report.md"]
    validate_plan(plan, CEILING)


def test_plan_refuses_unknown_tool_and_kind_mismatch() -> None:
    raw = mock_tool_plan(["geojson_analyzer"], CEILING)
    with pytest.raises(PlanError) as mismatch:
        validate_plan(raw, CEILING, "CSV")
    assert mismatch.value.code == "PLAN_INPUT_KIND_MISMATCH"
    validate_plan(raw, CEILING, "GEOJSON")
    bad = copy.deepcopy(raw)
    bad["tools"] = ["shell_exec"]
    bad["steps"][0]["tool"] = "shell_exec"
    with pytest.raises(PlanError) as unknown:
        validate_plan(bad, CEILING, "GEOJSON")
    assert unknown.value.code == "PLAN_UNKNOWN_TOOL"


def test_mock_tool_plans_validate_for_their_kind() -> None:
    validate_plan(mock_tool_plan(["hazard_analyzer", "resource_estimator", "blocked_roads", "report_generator"],
                                 CEILING, want_pdf=True), CEILING, "CSV")
    validate_plan(mock_tool_plan(["geojson_analyzer", "report_generator"], CEILING, want_pdf=True), CEILING, "GEOJSON")


def test_generated_scripts_pass_static_checks() -> None:
    check_script(build_tool_script(NEW_TOOLS, want_pdf=True))
    check_script(build_tool_script(["blocked_roads"]))


# ----- rule pack ----------------------------------------------------------------------------------------

def test_default_pack_hash_matches_its_body() -> None:
    data, pack = engine.load_default_pack()
    assert pack["pack_sha256"] == engine.pack_body_sha256(pack)
    assert pack["thresholds_label"] == "illustrative"
    assert data.endswith(b"\n")


def test_tampered_pack_is_refused(tmp_path: Path) -> None:
    data = engine.DEFAULT_PACK_PATH.read_bytes()
    tampered = data.replace(b'"water_depth_cm_gte": 100', b'"water_depth_cm_gte": 10')
    assert tampered != data
    with pytest.raises(RulePackError, match="hash mismatch"):
        parse_pack(tampered)
    no_hash = json.loads(data)
    del no_hash["pack_sha256"]
    with pytest.raises(RulePackError):
        parse_pack(json.dumps(no_hash).encode("utf-8"))


def test_pack_must_be_labelled_illustrative() -> None:
    pack = copy.deepcopy(_pack())
    pack["thresholds_label"] = "validated"
    pack["pack_sha256"] = engine.pack_body_sha256(pack)
    with pytest.raises(RulePackError, match="illustrative"):
        parse_pack(json.dumps(pack).encode("utf-8"))


def test_threshold_behaviour_follows_the_pack() -> None:
    records = [
        {"row": 1, "district": "A", "water_depth_cm": 49.9},
        {"row": 2, "district": "A", "water_depth_cm": 50.0},
        {"row": 3, "district": "B", "water_depth_cm": 99.9},
        {"row": 4, "district": "B", "water_depth_cm": 100.0},
        {"row": 5, "district": "C", "water_depth_cm": None},
    ]
    result = evaluate_hazards(records, _pack())
    severities = [item["severity"] for item in result["results"]]
    assert severities == ["LOW", "MEDIUM", "MEDIUM", "HIGH", "UNKNOWN"]
    assert result["road_blocked_candidates"] == 3  # 50.0, 99.9 and 100.0 are all at or above 50 cm
    assert result["rows_unknown_depth"] == 1
    assert result["counts_by_severity"] == {"HIGH": 1, "LOW": 1, "MEDIUM": 2, "UNKNOWN": 1}


def test_hazard_output_is_labelled_illustrative_and_inferred() -> None:
    result = evaluate_hazards(engine.records_from_csv_bytes(RICH_CSV), _pack())
    assert result["data_class"] == "INFERRED_FACT"
    assert result["thresholds"]["label"] == "illustrative"
    assert result["thresholds"]["status"].startswith("ILLUSTRATIVE")
    assert result["rule_pack"]["sha256"] == _pack()["pack_sha256"]
    assert all(rule["label"] == "illustrative" for rule in result["thresholds"]["rules"])


def test_hazard_evaluation_is_deterministic() -> None:
    pack = _pack()
    records = engine.records_from_csv_bytes(RICH_CSV)
    first = engine.canonical_json(evaluate_hazards(records, pack))
    second = engine.canonical_json(evaluate_hazards(list(records), pack))
    shuffled = engine.canonical_json(evaluate_hazards(list(reversed(records)), pack))
    assert first == second == shuffled


def test_resource_estimate_uses_pack_ratios() -> None:
    estimate = estimate_resources(engine.records_from_csv_bytes(RICH_CSV), _pack())
    assert estimate["data_class"] == "SIMULATED_FACT"
    assert estimate["label"].startswith("ILLUSTRATIVE")
    assert estimate["inputs"]["affected_rows"] == 3
    assert estimate["estimates"] == {
        "households_affected": 3, "people_estimated": 12, "water_packs": 3, "food_packs": 3,
        "shelter_kits": 2, "drinking_water_litres_total": 108,
    }
    assert estimate["not_for_operational_use"] is True


def test_script_matches_engine_for_hazard_and_resources(tmp_path: Path) -> None:
    pack_bytes = engine.DEFAULT_PACK_PATH.read_bytes()
    script = build_tool_script(["hazard_analyzer", "resource_estimator"])
    done = _run_script(tmp_path / "run", script, {"dataset.csv": RICH_CSV, "rule_pack.json": pack_bytes})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    out = tmp_path / "run" / "out"
    pack = _pack()
    records = engine.records_from_csv_bytes(RICH_CSV)
    hazard = json.loads((out / "hazard_results.json").read_text(encoding="utf-8"))
    resource = json.loads((out / "resource_estimate.json").read_text(encoding="utf-8"))
    assert hazard == json.loads(json.dumps(evaluate_hazards(records, pack)))
    assert resource == json.loads(json.dumps(estimate_resources(records, pack)))


def test_hazard_output_must_cite_the_staged_pack(tmp_path: Path) -> None:
    pack = _pack()
    doc = evaluate_hazards(engine.records_from_csv_bytes(RICH_CSV), pack)
    path = tmp_path / "hazard_results.json"
    path.write_bytes(engine.canonical_json(doc))
    artifact = ArtifactFile(name="hazard_results.json", path=str(path), sha256=_sha(path), size_bytes=path.stat().st_size)
    verified = validate_outputs([artifact], ["hazard_results.json"], tmp_path, pack_sha256=pack["pack_sha256"])
    assert verified[0].name == "hazard_results.json"
    with pytest.raises(OutputRejected) as wrong:
        validate_outputs([artifact], ["hazard_results.json"], tmp_path, pack_sha256="0" * 64)
    assert wrong.value.code == "OUTPUT_HASH_MISMATCH"
    with pytest.raises(OutputRejected):
        validate_outputs([artifact], ["hazard_results.json"], tmp_path, pack_sha256=None)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----- blocked roads and GeoJSON scripts ----------------------------------------------------------------

def test_blocked_roads_script_lists_blocked_rows_and_neutralises_cells(tmp_path: Path) -> None:
    done = _run_script(tmp_path / "br", build_tool_script(["blocked_roads"]), {"dataset.csv": RICH_CSV})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    lines = (tmp_path / "br" / "out" / "blocked_roads.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "row,district,road_status,water_depth_cm"
    assert len(lines) == 1 + 4  # rows 1, 3, 4 (closed), 6
    assert lines[2].startswith("3,'=Tebet,blocked,")


def test_blocked_roads_needs_a_road_column(tmp_path: Path) -> None:
    done = _run_script(tmp_path / "nr", build_tool_script(["blocked_roads"]),
                       {"dataset.csv": b"district,water_depth_cm\nKemang,35\n"})
    assert done.returncode != 0
    assert b"road_status" in done.stderr


def test_geojson_script_summary(tmp_path: Path) -> None:
    from tests.test_dataset_reject_geojson import GEO_OK
    done = _run_script(tmp_path / "gj", build_tool_script(["geojson_analyzer"]), {"dataset.geojson": GEO_OK})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    summary = json.loads((tmp_path / "gj" / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["feature_count"] == 4
    assert summary["geometry_types"] == {"LineString": 1, "Point": 1, "Polygon": 1, "null": 1}
    assert summary["bounding_box"] == [106.7, -6.3, 106.9, -6.1]
    assert summary["property_counts"] == {"blocked": 1, "capacity": 1, "name": 3}


# ----- PDF ----------------------------------------------------------------------------------------------

def test_pdf_report_is_valid_and_passes_artifact_validator(tmp_path: Path) -> None:
    pack_bytes = engine.DEFAULT_PACK_PATH.read_bytes()
    tools = ["hazard_analyzer", "report_generator"]
    script = build_tool_script(tools, want_pdf=True)
    done = _run_script(tmp_path / "pdf", script, {"dataset.csv": RICH_CSV, "rule_pack.json": pack_bytes})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    out = tmp_path / "pdf" / "out"
    pdf = (out / "situation_report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) < 10 * 1024 * 1024
    check_artifact("situation_report.pdf", pdf)
    _check_xref(pdf)
    md = (out / "situation_report.md").read_text(encoding="utf-8")
    assert "INFERRED_FACT" in md

    path = out / "situation_report.pdf"
    artifact = ArtifactFile(name="situation_report.pdf", path=str(path), sha256=_sha(path), size_bytes=len(pdf))
    verified = validate_outputs([artifact], ["situation_report.pdf"], tmp_path / "pdf")
    assert verified[0].type == "pdf"


def _check_xref(pdf: bytes) -> None:
    start = int(pdf.rsplit(b"startxref", 1)[1].split()[0])
    assert pdf[start:start + 4] == b"xref"
    entries = pdf[start:].split(b"\n")
    count = int(entries[1].split()[1])
    for number in range(1, count):
        offset = int(entries[2 + number][:10])
        assert pdf[offset:].startswith(f"{number} 0 obj".encode("ascii")), number


def test_pdf_writer_escapes_text_and_wraps_pages(tmp_path: Path) -> None:
    namespace: dict[str, Any] = {"os": os, "log": lambda message: None}
    from app.agent.mock_script import PDF_WRITER
    exec(PDF_WRITER, namespace)
    lines = ["a (b) c\\d é"] + ["line %d" % i for i in range(120)] + ["x" * 300]
    target = tmp_path / "t.pdf"
    namespace["write_pdf"](str(target), lines)
    data = target.read_bytes()
    assert b"a \\(b\\) c\\\\d ?" in data
    assert data.count(b" Tj T*") >= 121
    assert data.count(b"/Type /Page ") == 3
    _check_xref(data)


def test_pdf_limit_matches_sandbox_rule() -> None:
    assert ARTIFACT_RULES["situation_report.pdf"].max_bytes == 10 * 1024 * 1024
    assert outputs_mod.OUTPUT_RULES["situation_report.pdf"].max_bytes == 10 * 1024 * 1024
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024
