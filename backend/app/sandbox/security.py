"""Pure validation helpers for sandbox inputs and outputs (SDD 9.3, 17.2, 17.4).

Nothing in this module touches Docker or the filesystem.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.sandbox.errors import ArtifactRejected, SandboxInputError

KIB = 1024
MIB = 1024 * KIB

OUTPUT_EXCERPT_BYTES = 64 * KIB     # stdout/stderr excerpt limit (docs/api.md section 3)
MAX_SCRIPT_BYTES = 64 * KIB         # Python source limit (SDD 17.2)
MAX_INPUT_BYTES = 10 * MIB          # dataset upload limit (docs/api.md section 3)
MAX_INPUT_FILES = 8
MAX_OUTPUT_STREAM_BYTES = 40 * MIB  # hard cap on the tar stream read back from the sandbox

ALLOWED_ARTIFACT_KINDS = frozenset({"csv", "json", "png", "pdf", "md", "py", "log"})

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PDF_SIGNATURE = b"%PDF"

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_INPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_RESERVED_INPUT_NAMES = frozenset({"task.py", "out"})


@dataclass(frozen=True)
class ArtifactRule:
    kind: str          # one of ALLOWED_ARTIFACT_KINDS
    max_bytes: int


# Server-side allowlist. Agent-supplied names are never used as paths; a name must match exactly.
ARTIFACT_RULES: dict[str, ArtifactRule] = {
    "summary.json": ArtifactRule("json", 1 * MIB),
    "situation_report.md": ArtifactRule("md", 10 * MIB),
    "chart.png": ArtifactRule("png", 5 * MIB),
    "affected_areas.csv": ArtifactRule("csv", 5 * MIB),
    "blocked_roads.csv": ArtifactRule("csv", 5 * MIB),
    "situation_report.pdf": ArtifactRule("pdf", 10 * MIB),
    "hazard_results.json": ArtifactRule("json", 5 * MIB),
    "resource_estimate.json": ArtifactRule("json", 1 * MIB),
}


def artifact_rule(name: str) -> ArtifactRule:
    """Return the rule for an allowlisted artifact name, or raise ArtifactRejected."""
    if not isinstance(name, str):
        raise ArtifactRejected("artifact name must be a string")
    rule = ARTIFACT_RULES.get(name)
    if rule is None:
        raise ArtifactRejected(f"artifact name not allowlisted: {name!r}")
    return rule


def check_artifact(name: str, data: bytes) -> ArtifactRule:
    """Validate name, size, and content (magic bytes or strict UTF-8 parse). Returns the matched rule."""
    rule = artifact_rule(name)
    if len(data) > rule.max_bytes:
        raise ArtifactRejected(f"{name} exceeds size limit ({len(data)} > {rule.max_bytes} bytes)")

    if rule.kind == "png":
        if not data.startswith(PNG_SIGNATURE):
            raise ArtifactRejected(f"{name} is not a PNG (magic bytes mismatch)")
        return rule
    if rule.kind == "pdf":
        if not data.startswith(PDF_SIGNATURE):
            raise ArtifactRejected(f"{name} is not a PDF (magic bytes mismatch)")
        return rule

    # csv, json, md, py, log: must be UTF-8 text without NUL bytes.
    if b"\x00" in data:
        raise ArtifactRejected(f"{name} contains NUL bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactRejected(f"{name} is not valid UTF-8") from exc
    if rule.kind == "json":
        try:
            json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ArtifactRejected(f"{name} is not parseable JSON") from exc
    return rule


def validate_input_name(name: str) -> str:
    """Input names are plain file names staged into /workspace. No paths, no reserved names."""
    if not isinstance(name, str) or not _INPUT_NAME_RE.fullmatch(name):
        raise SandboxInputError(f"invalid input name: {name!r}")
    if name in _RESERVED_INPUT_NAMES:
        raise SandboxInputError(f"reserved input name: {name!r}")
    return name


def validate_inputs(inputs: Mapping[str, bytes]) -> None:
    """Check count, names, and total size of the staged inputs."""
    if len(inputs) > MAX_INPUT_FILES:
        raise SandboxInputError(f"too many input files (max {MAX_INPUT_FILES})")
    total = 0
    for name, data in inputs.items():
        validate_input_name(name)
        total += len(data)
    if total > MAX_INPUT_BYTES:
        raise SandboxInputError(f"inputs exceed {MAX_INPUT_BYTES} bytes in total")


def validate_script(script: str) -> bytes:
    """Return the UTF-8 bytes of the script, or raise if it is too large."""
    data = script.encode("utf-8")
    if len(data) > MAX_SCRIPT_BYTES:
        raise SandboxInputError(f"script exceeds {MAX_SCRIPT_BYTES} bytes")
    return data


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def neutralize_csv_cell(value: str) -> str:
    """Prefix a text cell with a single quote when it could be read as a spreadsheet formula (SDD 17.2).

    Apply to text cells only. Numeric values should be written as numbers, not passed here.
    """
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def neutralize_csv_row(row: Sequence[object]) -> list[object]:
    """Neutralize every str cell in a row. Non-string cells are returned unchanged."""
    return [neutralize_csv_cell(cell) if isinstance(cell, str) else cell for cell in row]
