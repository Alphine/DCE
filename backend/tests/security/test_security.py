"""Pure validation: artifact names, magic bytes, size limits, input names, CSV formula neutralizer."""

from __future__ import annotations

import pytest

from app.sandbox.errors import ArtifactRejected, SandboxInputError
from app.sandbox.security import (
    ARTIFACT_RULES,
    MAX_INPUT_BYTES,
    MAX_SCRIPT_BYTES,
    check_artifact,
    neutralize_csv_cell,
    neutralize_csv_row,
    validate_input_name,
    validate_inputs,
    validate_script,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4\n%%EOF"


# -- name allowlist ----------------------------------------------------------

@pytest.mark.parametrize("name", list(ARTIFACT_RULES))
def test_allowlisted_names_are_accepted(name: str) -> None:
    assert name in ARTIFACT_RULES


@pytest.mark.parametrize(
    "name",
    [
        "../summary.json",
        "out/chart.png",
        "/etc/passwd",
        "Summary.json",
        "summary.json ",
        "chart.png.exe",
        "task.py",
        "",
        "evil.sh",
    ],
)
def test_names_outside_allowlist_are_rejected(name: str) -> None:
    with pytest.raises(ArtifactRejected):
        check_artifact(name, b"{}")


def test_non_string_name_is_rejected() -> None:
    with pytest.raises(ArtifactRejected):
        check_artifact(None, b"{}")  # type: ignore[arg-type]


# -- magic bytes and content -------------------------------------------------

def test_png_requires_png_signature() -> None:
    check_artifact("chart.png", PNG)
    with pytest.raises(ArtifactRejected):
        check_artifact("chart.png", b"GIF89a" + b"\x00" * 10)


def test_png_signature_checked_even_when_text_is_given() -> None:
    with pytest.raises(ArtifactRejected):
        check_artifact("chart.png", b"not a png at all")


def test_json_must_be_valid_utf8_json() -> None:
    check_artifact("summary.json", b'{"ok": true}')
    with pytest.raises(ArtifactRejected):
        check_artifact("summary.json", b"{not json")
    with pytest.raises(ArtifactRejected):
        check_artifact("summary.json", b'{"x": "\xff"}')


def test_markdown_and_csv_must_be_utf8_text() -> None:
    check_artifact("situation_report.md", b"# Report\nWater depth ok")
    check_artifact("affected_areas.csv", b"district,count\nKemang,3\n")
    with pytest.raises(ArtifactRejected):
        check_artifact("blocked_roads.csv", b"a,b\n\xff\xfe\n")


def test_nul_bytes_rejected_in_text_artifacts() -> None:
    with pytest.raises(ArtifactRejected):
        check_artifact("situation_report.md", b"ok\x00hidden")


def test_pdf_signature_helper_rule_kind() -> None:
    # PDF is an allowed kind even though no allowlisted name uses it yet. The magic check is exercised here
    # by temporarily adding a rule, so the code path stays covered.
    from app.sandbox import security

    security.ARTIFACT_RULES["report.pdf"] = security.ArtifactRule("pdf", 10 * 1024 * 1024)
    try:
        check_artifact("report.pdf", PDF)
        with pytest.raises(ArtifactRejected):
            check_artifact("report.pdf", b"<html>")
    finally:
        del security.ARTIFACT_RULES["report.pdf"]


# -- size limits (SDD 17.2) --------------------------------------------------

def test_size_limits_match_sdd_17_2() -> None:
    assert ARTIFACT_RULES["summary.json"].max_bytes == 1 * 1024 * 1024
    assert ARTIFACT_RULES["chart.png"].max_bytes == 5 * 1024 * 1024
    assert ARTIFACT_RULES["affected_areas.csv"].max_bytes == 5 * 1024 * 1024
    assert ARTIFACT_RULES["situation_report.md"].max_bytes == 10 * 1024 * 1024


def test_oversize_png_is_rejected() -> None:
    too_big = PNG + b"\x00" * (5 * 1024 * 1024)
    with pytest.raises(ArtifactRejected, match="size limit"):
        check_artifact("chart.png", too_big)


def test_exact_limit_is_accepted() -> None:
    limit = ARTIFACT_RULES["summary.json"].max_bytes
    payload = b'"' + b"a" * (limit - 2) + b'"'
    assert len(payload) == limit
    check_artifact("summary.json", payload)


# -- input names and sizes ---------------------------------------------------

@pytest.mark.parametrize("name", ["flood.csv", "dataset_v2.csv", "a.b-c_d.csv"])
def test_plain_input_names_accepted(name: str) -> None:
    assert validate_input_name(name) == name


@pytest.mark.parametrize("name", ["../x.csv", "a/b.csv", ".hidden", "task.py", "out", "", "x" * 65, "sp ace.csv"])
def test_unsafe_input_names_rejected(name: str) -> None:
    with pytest.raises(SandboxInputError):
        validate_input_name(name)


def test_input_total_size_limit() -> None:
    with pytest.raises(SandboxInputError):
        validate_inputs({"a.csv": b"x" * (MAX_INPUT_BYTES // 2 + 1), "b.csv": b"x" * (MAX_INPUT_BYTES // 2 + 1)})


def test_script_size_limit() -> None:
    assert validate_script("x = 1") == b"x = 1"
    with pytest.raises(SandboxInputError):
        validate_script("#" * (MAX_SCRIPT_BYTES + 1))


# -- CSV formula neutralizer -------------------------------------------------

@pytest.mark.parametrize("value", ["=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_formula_prefixes_get_a_single_quote(value: str) -> None:
    assert neutralize_csv_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["Kemang", "", "a=b", "12", "district"])
def test_plain_text_is_unchanged(value: str) -> None:
    assert neutralize_csv_cell(value) == value


def test_row_neutralizer_leaves_non_strings_alone() -> None:
    assert neutralize_csv_row(["=x", 3, None, "ok"]) == ["'=x", 3, None, "ok"]
