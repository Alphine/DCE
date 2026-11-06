#!/usr/bin/env python3
"""Disaster Commander Edge smoke test (standard library only).

Runs after the server starts. Checks, in order:
  1. GET  /api/health                      -> 200, {"status": "ok"}
  2. POST /api/auth/login                  -> 200, sets the dce_session cookie
  3. GET  /api/dashboard/summary           -> 200, has datasets/tasks/sandbox keys
  4. POST /api/datasets (sample CSV)       -> 201, dataset returned with profile

Usage:
  DCE_SEED_PASSWORD='...' python scripts/smoke.py
  python scripts/smoke.py --base-url https://commander.basyid.dev

The seed password is read only from the DCE_SEED_PASSWORD environment variable.
It is never printed, logged, or put in a URL. Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = REPO_ROOT / "datasets" / "samples" / "flood_incidents_sample.csv"
SMOKE_USER = "analyst"  # seed account with the Analyst role (api.md section 10)
TIMEOUT_S = 15


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def record(self, name: str, ok: bool, detail: str) -> bool:
        self.rows.append((name, "PASS" if ok else "FAIL", detail))
        return ok

    def print_table(self) -> None:
        name_w = max(len(r[0]) for r in self.rows) if self.rows else 10
        detail_w = max(len(r[2]) for r in self.rows) if self.rows else 10
        line = "+-" + "-" * name_w + "-+------+-" + "-" * detail_w + "-+"
        print(line)
        print(f"| {'CHECK'.ljust(name_w)} | RES  | {'DETAIL'.ljust(detail_w)} |")
        print(line)
        for name, res, detail in self.rows:
            print(f"| {name.ljust(name_w)} | {res.ljust(4)} | {detail.ljust(detail_w)} |")
        print(line)


def request(opener, method: str, url: str, body: bytes | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def error_code(payload: bytes) -> str:
    try:
        return json.loads(payload)["error"]["code"]
    except Exception:  # noqa: BLE001 - diagnostic only
        return "unparsed"


def multipart_csv(field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n",
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n',
        "Content-Type: text/csv\r\n\r\n",
    ]
    body = "".join(parts).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("DCE_SMOKE_BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    password = os.environ.get("DCE_SEED_PASSWORD", "")
    check = Check()

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # 1. Health
    status, body = request(opener, "GET", f"{base}/api/health")
    ok = status == 200 and json.loads(body or b"{}").get("status") == "ok"
    check.record("GET /api/health", ok, f"HTTP {status}")

    # 2. Login (needs the seed password)
    if not password:
        check.record("POST /api/auth/login", False, "DCE_SEED_PASSWORD not set")
        check.print_table()
        return 1
    login_body = json.dumps({"username": SMOKE_USER, "password": password}).encode("utf-8")
    status, body = request(opener, "POST", f"{base}/api/auth/login", login_body,
                           {"Content-Type": "application/json"})
    has_cookie = any(c.name == "dce_session" for c in jar)
    ok = status == 200 and has_cookie
    detail = f"HTTP {status}" + ("" if ok else f", {error_code(body)}")
    if status == 200 and not has_cookie:
        detail = "HTTP 200, no dce_session cookie"
    check.record("POST /api/auth/login", ok, detail)
    if not ok:
        check.print_table()
        return 1

    # 3. Dashboard summary (authenticated)
    status, body = request(opener, "GET", f"{base}/api/dashboard/summary")
    ok = False
    if status == 200:
        try:
            summary = json.loads(body)
            ok = all(k in summary for k in ("datasets", "tasks", "sandbox"))
        except json.JSONDecodeError:
            ok = False
    check.record("GET /api/dashboard/summary", ok, f"HTTP {status}")

    # 4. Upload the synthetic sample CSV
    if not SAMPLE_CSV.exists():
        check.record("POST /api/datasets", False, f"missing {SAMPLE_CSV.name}")
    else:
        payload, content_type = multipart_csv("file", SAMPLE_CSV.name, SAMPLE_CSV.read_bytes())
        status, body = request(opener, "POST", f"{base}/api/datasets", payload,
                               {"Content-Type": content_type})
        ok = status in (200, 201)
        detail = f"HTTP {status}"
        if ok:
            try:
                ds = json.loads(body)
                rows = ds.get("profile", {}).get("rows")
                detail += f", rows={rows}"
                ok = rows == 40
            except json.JSONDecodeError:
                ok = False
                detail += ", invalid JSON"
        else:
            detail += f", {error_code(body)}"
        check.record("POST /api/datasets", ok, detail)

    check.print_table()
    failed = [r for r in check.rows if r[1] == "FAIL"]
    print(f"\n{len(check.rows) - len(failed)}/{len(check.rows)} checks passed.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
