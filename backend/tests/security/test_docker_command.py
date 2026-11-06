"""DockerSandboxRunner command construction and inspect verification, without Docker.

These tests check the argv built for `docker create`, the `docker inspect` checks that gate a start, the
output tar parser, and the orphan selection. Nothing here runs a container.
"""

from __future__ import annotations

import copy
import io
import tarfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.docker_runner import (
    DEFAULT_SECCOMP_PATH,
    DockerSandboxRunner,
    build_create_argv,
    build_input_tar,
    parse_output_tar,
    verify_container_config,
)
from app.sandbox.errors import ArtifactRejected
from app.sandbox.sweeper import orphan_threshold_s, parse_listing, select_orphans

TASK_ID = str(uuid.UUID(int=1234567))
IMAGE = "dce-worker@sha256:" + "a" * 64
CREATED = 1_800_000_000


def _argv(**overrides: Any) -> list[str]:
    opts: dict[str, Any] = dict(
        task_id=TASK_ID, created_ts=CREATED, image=IMAGE, memory_mb=512, pids=64,
        timeout_s=30, seccomp_path=DEFAULT_SECCOMP_PATH,
    )
    opts.update(overrides)
    return build_create_argv(**opts)


def _flag_values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


# -- docker create argv --------------------------------------------------------

@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--network", "none"),
        ("--tmpfs", "/workspace:rw,noexec,nosuid,size=100m,mode=1777"),
        ("--cpus", "1"),
        ("--memory", "512m"),
        ("--memory-swap", "512m"),
        ("--pids-limit", "64"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--user", "65534:65534"),
        ("--ulimit", "nofile=256:256"),
        ("--ipc", "none"),
        ("--label", f"dce.task={TASK_ID}"),
        ("--label", f"dce.created={CREATED}"),
    ],
)
def test_create_argv_contains_required_flag(flag: str, value: str) -> None:
    argv = _argv()
    assert value in _flag_values(argv, flag), f"{flag} {value} missing"


def test_create_argv_has_read_only_rootfs() -> None:
    assert "--read-only" in _argv()


def test_create_argv_has_seccomp_profile_path() -> None:
    values = _flag_values(_argv(), "--security-opt")
    assert f"seccomp={DEFAULT_SECCOMP_PATH}" in values
    assert DEFAULT_SECCOMP_PATH.name == "profile.json"
    assert DEFAULT_SECCOMP_PATH.parent.name == "seccomp"


def test_create_argv_forbidden_flags_are_absent() -> None:
    argv = _argv()
    for forbidden in ("-v", "--volume", "--mount", "--bind", "--privileged", "--network=host", "--pid", "--ipc=host",
                      "--cap-add", "--device", "--security-opt=apparmor=unconfined", "seccomp=unconfined"):
        assert forbidden not in argv
    assert "host" not in _flag_values(argv, "--network")
    assert all(not a.startswith("--volume") and not a.startswith("--mount") for a in argv)
    assert "--privileged" not in argv


def test_create_argv_env_is_allowlist_only() -> None:
    envs = _flag_values(_argv(), "--env")
    assert sorted(e.split("=", 1)[0] for e in envs) == ["DCE_TASK_ID", "DCE_TIMEOUT_S"]


def test_create_argv_image_is_last_and_no_command_is_passed() -> None:
    argv = _argv()
    assert argv[-1] == IMAGE
    assert argv[0] == "create"


def test_create_argv_memory_follows_config() -> None:
    argv = _argv(memory_mb=768)
    assert "768m" in _flag_values(argv, "--memory")
    assert "768m" in _flag_values(argv, "--memory-swap")


def test_runner_refuses_missing_seccomp_profile(tmp_path: Path) -> None:
    from app.sandbox.errors import SandboxConfigError

    with pytest.raises(SandboxConfigError):
        DockerSandboxRunner(image=IMAGE, staging_root=tmp_path, seccomp_path=tmp_path / "missing.json")


def test_runner_name_and_concurrency(tmp_path: Path) -> None:
    runner = DockerSandboxRunner(image=IMAGE, staging_root=tmp_path, max_concurrent=2)
    assert runner.name == "docker"
    assert runner.max_concurrent == 2


# -- docker inspect verification -----------------------------------------------

def _good_inspect() -> dict[str, Any]:
    return {
        "Mounts": [],
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "Privileged": False,
            "PidsLimit": 64,
            "Binds": None,
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "NanoCpus": 1_000_000_000,
            "IpcMode": "none",
            "PidMode": "",
            "UsernsMode": "",
            "SecurityOpt": ["no-new-privileges", f"seccomp={DEFAULT_SECCOMP_PATH}"],
            "Tmpfs": {"/workspace": "rw,noexec,nosuid,size=100m,mode=1777"},
            "Ulimits": [{"Name": "nofile", "Soft": 256, "Hard": 256}],
        },
        "Config": {"User": "65534:65534", "Labels": {"dce.task": TASK_ID}},
    }


def _verify(info: dict[str, Any]) -> list[str]:
    return verify_container_config(info, task_id=TASK_ID, memory_mb=512, pids=64, seccomp_path=DEFAULT_SECCOMP_PATH)


def test_verification_passes_for_correct_configuration() -> None:
    assert _verify(_good_inspect()) == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("HostConfig", "NetworkMode"), "bridge"),
        (("HostConfig", "NetworkMode"), "host"),
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "CapDrop"), []),
        (("HostConfig", "Privileged"), True),
        (("HostConfig", "PidsLimit"), 512),
        (("HostConfig", "Binds"), ["/var/run/docker.sock:/var/run/docker.sock"]),
        (("HostConfig", "MemorySwap"), 1024 * 1024 * 1024),
        (("HostConfig", "IpcMode"), "host"),
        (("HostConfig", "SecurityOpt"), ["seccomp=unconfined"]),
        (("HostConfig", "Tmpfs"), {"/workspace": "rw"}),
        (("HostConfig", "CapAdd"), ["SYS_ADMIN"]),
        (("Config", "User"), "0:0"),
        (("Config", "Labels"), {"dce.task": "someone-else"}),
    ],
)
def test_verification_refuses_each_weakened_setting(path: tuple[str, str], value: object) -> None:
    info = copy.deepcopy(_good_inspect())
    info[path[0]][path[1]] = value
    assert _verify(info), f"expected a violation for {path}={value!r}"


def test_verification_refuses_any_mount() -> None:
    info = copy.deepcopy(_good_inspect())
    info["Mounts"] = [{"Type": "bind", "Source": "/home", "Destination": "/home"}]
    assert any("mounts" in p for p in _verify(info))


def test_verification_refuses_missing_seccomp() -> None:
    info = copy.deepcopy(_good_inspect())
    info["HostConfig"]["SecurityOpt"] = ["no-new-privileges"]
    assert any("seccomp" in p for p in _verify(info))


# -- input tar -------------------------------------------------------------------

def test_input_tar_contains_task_and_inputs_owned_by_run_user() -> None:
    data = build_input_tar(b"print(1)", {"flood.csv": b"a,b\n1,2\n"}, mtime=1)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        members = {m.name: m for m in tar.getmembers()}
        assert set(members) == {"task.py", "flood.csv"}
        assert all(m.uid == 65534 and m.gid == 65534 for m in members.values())
        assert tar.extractfile("task.py").read() == b"print(1)"  # type: ignore[union-attr]


# -- output tar parser ---------------------------------------------------------

def _out_tar(entries: list[tuple[str, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_output_tar_accepts_allowlisted_regular_files() -> None:
    data = _out_tar([("out", None), ("out/summary.json", b"{}")])
    assert parse_output_tar(data) == {"summary.json": b"{}"}


def test_output_tar_rejects_symlink() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="out/chart.png")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(ArtifactRejected):
        parse_output_tar(buf.getvalue())


def test_output_tar_rejects_path_outside_out() -> None:
    with pytest.raises(ArtifactRejected):
        parse_output_tar(_out_tar([("etc/summary.json", b"{}")]))


def test_output_tar_rejects_unlisted_name() -> None:
    with pytest.raises(ArtifactRejected):
        parse_output_tar(_out_tar([("out/evil.sh", b"rm")]))


def test_output_tar_rejects_oversize_member_before_reading() -> None:
    with pytest.raises(ArtifactRejected, match="size limit"):
        parse_output_tar(_out_tar([("out/summary.json", b"x" * (1024 * 1024 + 1))]))


def test_output_tar_rejects_nested_directory_entry() -> None:
    with pytest.raises(ArtifactRejected):
        parse_output_tar(_out_tar([("out", None), ("out/sub", None)]))


def test_output_tar_rejects_garbage_stream() -> None:
    with pytest.raises(ArtifactRejected):
        parse_output_tar(b"this is not a tar archive at all" * 10)


# -- orphan selection ----------------------------------------------------------

def test_orphan_threshold_is_timeout_plus_30_seconds() -> None:
    assert orphan_threshold_s(30) == 60


def test_parse_listing_handles_missing_and_bad_labels() -> None:
    text = "abc123def456\t1800000000\nfeedfacefeed\t\nbadbadbadbad\tnotanumber\n"
    assert parse_listing(text) == [
        ("abc123def456", 1_800_000_000),
        ("feedfacefeed", None),
        ("badbadbadbad", None),
    ]


def test_select_orphans_removes_old_and_unlabelled_keeps_active_and_recent() -> None:
    now = 1_000_000
    entries = [
        ("old", now - 61),        # older than timeout + 30: orphan
        ("recent", now - 10),     # keep
        ("active", now - 500),    # held by a live run in this process: keep
        ("unknown", None),        # no creation label: treat as orphan
    ]
    chosen = select_orphans(entries, now=now, max_age_s=60, active={"active"})
    assert chosen == ["old", "unknown"]
