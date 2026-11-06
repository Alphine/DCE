# Containment checklist (SDD 9.8, 9.7, 23.2, 23.4)

Maps each canonical test T01 to T12 to the command that runs it and the evidence it must produce. This feeds the demo video and the README.

Two evidence paths exist for each test:

- **API path (authoritative).** Submit the hostile task through the normal workflow, so the full SDD 9.7 bundle is recorded: container ID, `docker inspect` output, code hash, exit code, duration, audit IDs.
- **Manual path (reproduction).** Run the same payload directly with the §9.3 flag set, to show the kernel-level behavior on camera. It does not produce the audit chain.

Run the destructive tests (T02 to T04, T09) only on a disposable VM or a local Docker host (§9.8). On the live VM, run them only outside demo hours, and check T12 afterwards.

## Setup (once per VM session)

```bash
export BASE=https://commander.basyid.dev
export REPO=/srv/dce/app
export IMG="$(cat $REPO/deployment/vultr/worker-image.digest)"   # dce-worker@sha256:...
# Session cookie for the seed analyst account (password typed or read from the VM .env; never echoed)
curl -sS -c /tmp/dce-analyst.cookies -H 'Content-Type: application/json' \
  -d "{\"username\":\"analyst\",\"password\":\"$DCE_SEED_PASSWORD\"}" "$BASE/api/auth/login" -o /dev/null -w '%{http_code}\n'
```

Expect `200`. `/tmp` is used here only for a short-lived cookie jar; delete it after the demo.

Manual reproduction helper. Same flags as SDD 9.3. No `--rm`, so `docker inspect` still works afterwards. The helper removes the container at the end:

```bash
dce_run() {  # usage: dce_run <name> <python -c code>
  local name="manual-$1-$(date +%s)"
  docker run --name "$name" \
    --network none --read-only \
    --tmpfs /workspace:rw,noexec,nosuid,size=100m,mode=1777 \
    --cpus 1 --memory 512m --memory-swap 512m --pids-limit 64 \
    --cap-drop ALL --security-opt no-new-privileges \
    --security-opt seccomp=$REPO/sandbox/seccomp/profile.json \
    --user 65534:65534 --ulimit nofile=256:256 --ipc none \
    --label dce.task=manual --label dce.created="$(date +%s)" \
    --entrypoint python3 "$IMG" -c "$2"
  local rc=$?
  echo "--- exit=$rc"
  docker inspect --format 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}' "$name"
  docker rm "$name" >/dev/null
}
```

If the image has no `python3` on PATH, use the interpreter path in the image (check with `docker run --rm --entrypoint sh "$IMG" -c 'command -v python3 python'`).

---

## T01. Normal Python execution

| | |
| --- | --- |
| **API path** | Log in as `analyst`, create a task on the sample dataset, approve gate A as `approver`, approve gate B as `reviewer`. |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/agent/tasks/$TID" \| jq '{state, sandbox: {exit_code: .sandbox.exit_code, runner: .sandbox.runner, container_id: .sandbox.container_id}, code_sha256}'` |
| **Expected** | `"state": "COMPLETED"`, `exit_code` 0, `runner` `docker`. |
| **Artifact hash** | `curl -sS -b /tmp/dce-analyst.cookies -D - -o chart.png "$BASE/api/artifacts/$AID" \| grep -i x-content-sha256` then `sha256sum chart.png`. The two hashes must match. |
| **Manual** | Not needed. |
| **Evidence** | Full §9.7 bundle from the task record and the audit export. |

## T02. Infinite loop

| | |
| --- | --- |
| **API path** | Submit a task whose generated code is `while True: pass` (use the security harness, `backend/tests/security`, if present). |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/agent/tasks/$TID" \| jq '{state, duration_ms: .sandbox.duration_ms, timed_out: .sandbox.timed_out}'` |
| **Expected** | `"state": "TIMED_OUT"`, `timed_out` true, `duration_ms` about 30000. |
| **Manual** | `time dce_run t02 "while True: pass"` is a demonstration only. There is no dispatcher timeout in manual mode, so stop it with `docker kill` after 30 s and show the container being killed. |
| **Evidence** | Duration, `TIMED_OUT` state transition in audit, cleanup (see T10). |

## T03. Memory exhaustion

| | |
| --- | --- |
| **API path** | Task with code that allocates beyond 512 MB, for example `b = bytearray(700 * 1024 * 1024)` followed by a write loop. |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/agent/tasks/$TID" \| jq '{state, oom_killed: .sandbox.oom_killed, exit_code: .sandbox.exit_code}'` |
| **Expected** | `"state": "FAILED_SANDBOX"`, `oom_killed` true, `exit_code` 137. |
| **Manual** | `dce_run t03 "b = bytearray(b'x' * (700 * 1024 * 1024)); print('survived')"` |
| **Expected manual** | No `survived` in output. `OOMKilled=true ExitCode=137`. |
| **Evidence** | `docker inspect` `OOMKilled=true` (SDD 23.4). Host unaffected (see T12). |

## T04. Excessive process creation (fork bomb)

| | |
| --- | --- |
| **API path** | Task with code that forks in a loop, for example `import os` then `while True: os.fork()`. |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/agent/tasks/$TID" \| jq '{state, stderr: .sandbox.stderr_excerpt}'` |
| **Expected** | `"state": "FAILED_SANDBOX"`. Stderr contains a fork or resource error such as `Resource temporarily unavailable`. |
| **Manual** | `dce_run t04 "import os
while True: os.fork()"` (or on one line with `;`). The fork call fails once the 64-PID limit is hit. |
| **Expected manual** | Non-zero exit with an `OSError` (errno 11). The host does not slow down. |
| **Evidence** | Stderr excerpt. `cat /sys/fs/cgroup/pids.events` inside a run shows `max` events if you add that to the payload. Host unaffected (T12). |

## T05. Host filesystem read

| | |
| --- | --- |
| **API path** | Task that tries to read `/home`, `/root`, `/srv/dce`, and `/etc/passwd` on the host. |
| **Command** | `... \| jq -r '.sandbox.stdout_excerpt'` |
| **Expected** | Only `False` for each path, or a `FileNotFoundError` on stderr. No host usernames or DCE paths in output. |
| **Manual** | `dce_run t05 "import os; [print(p, os.path.exists(p)) for p in ['/home','/root','/srv/dce','/var/lib/docker','/var/run/docker.sock','/data']]"` |
| **Expected manual** | Every line ends with `False`. |
| **Evidence** | Stdout check (empty of host data). |

## T06. Secret access

| | |
| --- | --- |
| **API path** | Task that dumps the environment and searches for `DCE_`, `VULTR`, `KEY`, `SECRET`, and `TOKEN`. |
| **Command** | `... \| jq -r '.sandbox.stdout_excerpt' \| grep -Eic 'DCE_|VULTR|KEY|SECRET|TOKEN|PASSWORD'` |
| **Expected** | `0`. The environment holds only the allowlist (task ID, timeout). |
| **Manual** | `docker run --rm --network none --entrypoint env "$IMG" \| grep -Eic 'DCE_|VULTR|KEY|SECRET|TOKEN|PASSWORD'` (expect `0`) and `dce_run t06 "import os; print([p for p in ['/root/.ssh','/home','/etc/ssh'] if os.path.exists(p)])"` (expect `[]`). |
| **Evidence** | Env dump with allowlist only. `docker inspect` `.Config.Env` contains no secrets (SDD 9.5). |

## T07. Network access

| | |
| --- | --- |
| **API path** | Task that opens an HTTP connection to a control host, for example `urllib.request.urlopen('http://1.1.1.1', timeout=5)`. |
| **Command** | Read the stderr excerpt from the task record. |
| **Expected** | Connection error (`Network is unreachable` or `Errno -3`). State `FAILED_SANDBOX` with exit code 1. |
| **Manual** | `dce_run t07 "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=5)"` |
| **Host capture** | On the VM, during the run: `sudo tcpdump -ni any 'host 1.1.1.1' -c 5` (no packets from the worker IP). With `--network none` the worker has no interface except loopback, so zero packets is expected. |
| **Evidence** | Stderr, plus the capture output showing no packets. |

## T08. Malformed generated script

| | |
| --- | --- |
| **API path** | Task whose generated code has a syntax error, for example `def f(:`. |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/agent/tasks/$TID/artifacts" \| jq 'length'` |
| **Expected** | State `FAILED_SANDBOX`. Stderr has a `SyntaxError`. Artifact list length is `0`. |
| **Manual** | `dce_run t08 "def f(:"` (expect `SyntaxError`, exit 1). |
| **Evidence** | Stderr and an empty artifact list. |

## T09. Execution timeout (sleep 60)

| | |
| --- | --- |
| **API path** | Task whose code calls `time.sleep(60)`. |
| **Command** | `curl -sS -b /tmp/dce-analyst.cookies "$BASE/api/audit?limit=50" \| jq '.[] \| select(.action \| test("sandbox\|task.state")) \| {at, action, detail}'` (Reviewer role) |
| **Expected** | `TIMED_OUT` transition at about 30 s, with a matching audit record. |
| **Manual** | Same as T02 with `time.sleep(60)`. |
| **Evidence** | State transition in audit, with timestamps. |

## T10. Automatic container destruction after every run

| | |
| --- | --- |
| **Command** | `docker ps -a --filter label=dce.task --format '{{.ID}} {{.Names}} {{.Status}}'` |
| **Expected** | Empty output after T01 to T09. |
| **Orphan check** | `docker ps -a --filter label=dce.task -q \| xargs -r docker inspect --format '{{.Name}} {{.State.Status}}'` must print nothing. |
| **Per-container check** | For each container ID recorded in the task: `docker inspect <id>` returns `No such object`. |
| **Sweeper** | Force an orphan: `docker run -d --label dce.task=orphan-test --entrypoint sleep "$IMG" 600`, wait over the timeout plus 30 s (sweeper runs every 60 s), then confirm it is gone and the audit has a sweep record. |
| **Evidence** | Empty `docker ps -a` output with the label filter, and the audit entry for the sweep. |

## T11. Docker API access attempt from inside the worker

| | |
| --- | --- |
| **API path** | Task whose code tries the socket and the proxy. |
| **Manual** | `dce_run t11 "import os, urllib.request; print('sock', os.path.exists('/var/run/docker.sock')); urllib.request.urlopen('http://docker-socket-proxy:2375/containers/json', timeout=3)"` |
| **Expected manual** | `sock False`. The `urlopen` raises a URL or DNS error. Exit non-zero. |
| **Evidence** | Stderr, and the `sock False` line in stdout. |

## T12. Host availability after hostile tasks

| | |
| --- | --- |
| **Command** | Run after T02 to T04 (and again after the full set). The evidence folder is in the admin home, because `/srv/dce/backups` belongs to the `dce` user: `mkdir -p ~/dce-evidence && for i in $(seq 1 20); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' "$BASE/api/health"; sleep 1; done \| tee ~/dce-evidence/health-after-hostile.log` |
| **Expected** | All 20 lines start with `200`, and each `time_total` is below `1.000`. |
| **Local check** | `curl -s -w '%{http_code} %{time_total}\n' -o /dev/null http://127.0.0.1:8000/api/health` |
| **Service check** | `systemctl is-active caddy` and `docker compose -f $REPO/deployment/docker-compose.yml ps` both healthy. |
| **Evidence** | The health log file, with the 200 responses and sub-second timings. |

---

## Final acceptance (SDD 23.4 items that depend on this checklist)

- [ ] T01 to T12 each have a recorded evidence bundle or a manual transcript, saved under `docs/benchmarks/` or the demo folder.
- [ ] The audit chain verifies: `curl -sS -X POST -b <admin-cookies> "$BASE/api/audit/verify"` returns success (Admin role).
- [ ] The demo video shows at least one containment moment: T02 (timeout) or T03 (OOM kill).
- [ ] Container IDs and `docker inspect` output are saved alongside the screenshots for the slide deck (SDD 9.7).
