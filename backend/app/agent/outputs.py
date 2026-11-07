"""Output validation and artifact storage (SDD 17.2, 17.4, docs/api.md section 3 and 7)."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.util import sha256_file

MB = 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF"


class OutputRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OutputRule:
    type: str       # docs/api.md Artifact types
    max_bytes: int
    kind: str       # "json" | "text" | "png"


# Only these server-known names may be produced or stored (SDD 17.4: no agent-supplied names as paths).
OUTPUT_RULES: dict[str, OutputRule] = {
    "summary.json": OutputRule("json", 1 * MB, "json"),
    "situation_report.md": OutputRule("md", 10 * MB, "text"),
    "situation_report.pdf": OutputRule("pdf", 10 * MB, "pdf"),
    "chart.png": OutputRule("png", 5 * MB, "png"),
    "affected_areas.csv": OutputRule("csv", 5 * MB, "text"),
    "blocked_roads.csv": OutputRule("csv", 5 * MB, "text"),
    "hazard_results.json": OutputRule("json", 5 * MB, "json"),
    "resource_estimate.json": OutputRule("json", 1 * MB, "json"),
    "tsunami_results.json": OutputRule("json", 5 * MB, "json"),
}


@dataclass(frozen=True)
class VerifiedOutput:
    name: str
    type: str
    size_bytes: int
    sha256: str
    source_path: Path


def validate_outputs(artifacts: Iterable, expected: Iterable[str], data_dir: Path,
                     pack_sha256: str | None = None, tsunami_sha256: str | None = None) -> list[VerifiedOutput]:
    """Validate sandbox output files. `artifacts` are ArtifactFile-like objects with name/path/sha256/size_bytes.

    `pack_sha256` is the hash of the rule pack the server staged for this run. Hazard output must
    echo that hash, so output can never claim to come from a different rule pack.
    """
    root = data_dir.resolve()
    seen: dict[str, VerifiedOutput] = {}
    for item in artifacts:
        name = str(item.name)
        rule = OUTPUT_RULES.get(name)
        if rule is None or "/" in name or "\\" in name:
            raise OutputRejected("OUTPUT_NOT_ALLOWED", "An output file name is not on the allowed list.")
        if name in seen:
            raise OutputRejected("OUTPUT_NOT_ALLOWED", "Duplicate output file name.")
        source = Path(str(item.path))
        if source.is_symlink() or not source.is_file():
            raise OutputRejected("OUTPUT_PATH_INVALID", "Output path is not a regular file.")
        try:
            source.resolve().relative_to(root)
        except ValueError as exc:
            raise OutputRejected("OUTPUT_PATH_INVALID", "Output path is outside the data directory.") from exc
        digest, size = sha256_file(str(source))
        if size == 0:
            raise OutputRejected("OUTPUT_TYPE_MISMATCH", "Output file is empty.")
        if size > rule.max_bytes or size != int(item.size_bytes):
            raise OutputRejected("OUTPUT_TOO_LARGE", "Output file exceeds its size limit.")
        if digest != str(item.sha256):
            raise OutputRejected("OUTPUT_HASH_MISMATCH", "Output hash does not match the sandbox record.")
        _check_content(source, rule)
        if name == "hazard_results.json":
            _check_hazard_result(source, pack_sha256)
        if name == "tsunami_results.json":
            _check_hazard_result(source, tsunami_sha256)
        seen[name] = VerifiedOutput(name=name, type=rule.type, size_bytes=size, sha256=digest, source_path=source)

    for name in expected:
        if name not in seen:
            raise OutputRejected("OUTPUT_MISSING", f"Expected output is missing: {name}")
    return list(seen.values())


def _check_hazard_result(path: Path, pack_sha256: str | None) -> None:
    """Hazard output is INFERRED_FACT and must cite the rule pack the server staged (SDD 11.3, 16.3)."""
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OutputRejected("OUTPUT_TYPE_MISMATCH", "Hazard output does not parse.") from exc
    rule_pack = doc.get("rule_pack") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get("data_class") != "INFERRED_FACT" or not isinstance(rule_pack, dict):
        raise OutputRejected("OUTPUT_TYPE_MISMATCH", "Hazard output has the wrong shape or data class.")
    if pack_sha256 is None or rule_pack.get("sha256") != pack_sha256:
        raise OutputRejected("OUTPUT_HASH_MISMATCH", "Hazard output does not cite the staged rule pack.")


def _check_content(path: Path, rule: OutputRule) -> None:
    if rule.kind == "png":
        with path.open("rb") as fh:
            if fh.read(len(PNG_MAGIC)) != PNG_MAGIC:
                raise OutputRejected("OUTPUT_TYPE_MISMATCH", "File is not a PNG.")
    elif rule.kind == "pdf":
        with path.open("rb") as fh:
            if fh.read(len(PDF_MAGIC)) != PDF_MAGIC:
                raise OutputRejected("OUTPUT_TYPE_MISMATCH", "File is not a PDF.")
    elif rule.kind == "json":
        try:
            json.loads(path.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OutputRejected("OUTPUT_TYPE_MISMATCH", "JSON output does not parse.") from exc
    else:
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OutputRejected("OUTPUT_TYPE_MISMATCH", "Text output is not UTF-8.") from exc


def store_outputs(outputs: list[VerifiedOutput], data_dir: Path, task_id: str) -> list[dict]:
    """Copy verified outputs to DCE_DATA_DIR/artifacts/<task_id>/<uuid>.<ext> and re-verify the hash."""
    target_dir = data_dir / "artifacts" / task_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stored: list[dict] = []
    try:
        for out in outputs:
            artifact_id = str(uuid.uuid4())
            ext = out.type
            final = target_dir / f"{artifact_id}.{ext}"
            tmp = target_dir / f"{artifact_id}.tmp"
            shutil.copyfile(out.source_path, tmp)
            digest, size = sha256_file(str(tmp))
            if digest != out.sha256 or size != out.size_bytes:
                tmp.unlink(missing_ok=True)
                raise OutputRejected("OUTPUT_HASH_MISMATCH", "Copy did not match the verified hash.")
            os.replace(tmp, final)
            stored.append({
                "id": artifact_id,
                "name": out.name,
                "type": out.type,
                "size_bytes": out.size_bytes,
                "sha256": out.sha256,
                "storage_path": f"artifacts/{task_id}/{artifact_id}.{ext}",
            })
    except BaseException:
        for item in stored:
            (data_dir / item["storage_path"]).unlink(missing_ok=True)
        raise
    return stored
