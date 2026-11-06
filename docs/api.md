# DCE API Contract (v1.6)

This is the shared contract between the backend, the sandbox, and the frontend. Every implementer must follow it exactly. If something is missing, stop and report it rather than guessing.

Base path: `/api`. Frontend and API share one origin (SDD §5.4).

## 1. Conventions

- JSON in and out, UTF-8. Timestamps are ISO 8601 UTC strings (`2026-11-05T14:31:44Z`).
- IDs are UUIDv4 strings.
- Errors use one shape:

```json
{"error": {"code": "QUOTA_EXCEEDED", "message": "Daily agent task quota reached.", "request_id": "req_..."}}
```

Error codes: `UNAUTHENTICATED`, `FORBIDDEN`, `SELF_APPROVAL_NOT_ALLOWED`, `QUOTA_EXCEEDED`, `RATE_LIMITED`, `VALIDATION_FAILED`, `NOT_FOUND`, `CONFLICT`, `INVALID_STATE`, `UNAVAILABLE`, `INTERNAL`.

- Auth: session cookie `dce_session` (HttpOnly, SameSite=Strict, Path=/; `Secure` only when `DCE_COOKIE_SECURE=true`).
- Roles, lowest to highest: `Viewer` < `Analyst` < `Reviewer` < `Approver` < `Admin`. A role includes all lower roles except where noted.
- Separation of duties: nobody may approve their own dataset, own observation, or own agent gate. Attempts return `403 SELF_APPROVAL_NOT_ALLOWED`.

## 2. Endpoints

| Method | Path | Min role | Purpose |
|---|---|---|---|
| GET | `/api/health` | public | Liveness: `{"status":"ok"}` only |
| POST | `/api/auth/login` | public (rate limited) | Start session |
| POST | `/api/auth/logout` | Viewer | End session (204) |
| GET | `/api/auth/me` | Viewer | Current user |
| GET | `/api/dashboard/summary` | Viewer | Counts, runner status, quota |
| GET | `/api/datasets` | Viewer | List datasets |
| POST | `/api/datasets` | Analyst | Upload CSV (multipart) |
| GET | `/api/datasets/{id}` | Viewer | Dataset with profile |
| POST | `/api/datasets/{id}/approve` | Reviewer (not uploader) | Set status APPROVED |
| POST | `/api/agent/tasks` | Analyst (quota) | Create agent task |
| GET | `/api/agent/tasks` | Viewer | List own tasks (Reviewer+ sees all) |
| GET | `/api/agent/tasks/{id}` | Owner or Reviewer+ | Task detail |
| GET | `/api/agent/tasks/{id}/events` | Owner or Reviewer+ | SSE stream |
| POST | `/api/agent/tasks/{id}/approve` | Approver (not owner) for gate A; Reviewer+ (not owner) for gate B | Gate decision |
| POST | `/api/agent/tasks/{id}/cancel` | Owner or Admin | Cancel |
| GET | `/api/agent/tasks/{id}/artifacts` | Owner or Reviewer+ | Artifacts of a task |
| GET | `/api/artifacts/{id}` | Owner or Reviewer+ | Download file (`X-Content-SHA256` header) |
| GET | `/api/audit` | Reviewer | Audit records (`?limit=&offset=`) |
| POST | `/api/audit/verify` | Admin | Verify hash chain |

Request bodies (added after the deployment review):
- `POST /api/auth/login`: JSON `{"username": "...", "password": "..."}`.
- `POST /api/datasets`: multipart form, file field named `file`, plus optional text field `name`.

Rate limiting: 10 login attempts per IP per minute; 20 agent task creations per user per day (`DCE_QUOTA_TASKS_PER_DAY`); 1 agent task creation per user per 30 seconds.

## 3. Resource shapes

### User
```json
{"id": "uuid", "username": "analyst", "role": "Analyst"}
```

### Dataset
```json
{
  "id": "uuid",
  "name": "Flood incidents Jakarta sample",
  "filename": "flood_incidents_sample.csv",
  "size_bytes": 1234,
  "sha256": "hex",
  "status": "PENDING_VALIDATION | APPROVED | REJECTED",
  "owner": {"id": "uuid", "username": "analyst"},
  "profile": {
    "rows": 40,
    "columns": [{"name": "district", "dtype": "string", "nulls": 0}],
    "preview": [{"district": "Kemang", "water_depth_cm": 35}]
  },
  "created_at": "2026-11-05T10:00:00Z"
}
```
Upload limit: 10 MB, CSV only, UTF-8 with header row. Preview is at most 5 rows. The profile is computed server-side with the standard library only.

### Plan (produced by the planner, validated against the tool registry)
```json
{
  "tools": ["csv_analyzer", "chart_generator", "report_generator"],
  "steps": [
    {"id": "s1", "description": "Profile dataset and count flooded districts", "tool": "csv_analyzer"},
    {"id": "s2", "description": "Count blocked roads and affected population", "tool": "csv_analyzer"},
    {"id": "s3", "description": "Plot water depth by district", "tool": "chart_generator"},
    {"id": "s4", "description": "Write situation report", "tool": "report_generator"}
  ],
  "limits": {"timeout_s": 30, "memory_mb": 512, "pids": 64},
  "expected_outputs": ["summary.json", "chart.png", "situation_report.md"],
  "assumptions": ["Water depth above 30 cm is treated as flooded (illustrative threshold)."],
  "data_class": "SIMULATED_FACT"
}
```

### AgentTask
```json
{
  "id": "uuid",
  "instruction": "Analyze this flood incident dataset...",
  "dataset_id": "uuid",
  "requested_outputs": ["affected_areas", "blocked_roads", "situation_report"],
  "state": "AWAITING_APPROVAL",
  "plan": null,
  "code_sha256": null,
  "sandbox": null,
  "artifacts": [],
  "approvals": [],
  "owner": {"id": "uuid", "username": "analyst"},
  "error_reason": null,
  "created_at": "2026-11-05T10:00:00Z",
  "updated_at": "2026-11-05T10:00:05Z"
}
```

`sandbox` when present:
```json
{
  "runner": "docker",
  "container_id": "abc123 or null for local runner",
  "exit_code": 0,
  "duration_ms": 4210,
  "timed_out": false,
  "oom_killed": false,
  "stdout_excerpt": "first 64 KB",
  "stderr_excerpt": "first 64 KB",
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

### Approval entry
```json
{"gate": "A", "decision": "approve", "approver": {"id": "uuid", "username": "approver"}, "role": "Approver", "at": "2026-11-05T10:01:00Z", "note": "ok"}
```

### Artifact
```json
{
  "id": "uuid",
  "task_id": "uuid",
  "name": "chart.png",
  "type": "png",
  "size_bytes": 20480,
  "sha256": "hex",
  "created_at": "2026-11-05T10:02:00Z",
  "download_url": "/api/artifacts/uuid"
}
```
Allowed types: `csv`, `json`, `png`, `pdf`, `md`, `py`, `log`. Server-generated file names only.

### AuditRecord
```json
{"id": 1, "at": "2026-11-05T10:00:00Z", "actor": "analyst", "action": "agent_task.created", "subject": "uuid", "detail": {"state": "PLANNING"}, "prev_hash": "hex", "row_hash": "hex"}
```
Audit never stores secrets, raw dataset contents, or full prompts. It stores IDs and hashes.

### Dashboard summary
```json
{
  "datasets": {"total": 3, "approved": 1},
  "tasks": {"by_state": {"COMPLETED": 2, "AWAITING_APPROVAL": 1}},
  "artifacts": 6,
  "sandbox": {"runner": "docker", "max_concurrent": 1, "running": 0},
  "inference": {"mode": "mock", "model": "mock-planner"},
  "quota": {"used_today": 3, "limit": 20},
  "env": "development"
}
```

## 4. Task state machine

States: `PLANNING`, `FAILED_PLANNING`, `AWAITING_APPROVAL`, `REJECTED`, `QUEUED`, `CANCELLED`, `RUNNING`, `TIMED_OUT`, `FAILED_SANDBOX`, `OUTPUT_VALIDATING`, `REJECTED_OUTPUT`, `AWAITING_REVIEW`, `COMPLETED`, `ORPHANED`.

Terminal: `FAILED_PLANNING`, `REJECTED`, `CANCELLED`, `TIMED_OUT`, `FAILED_SANDBOX`, `REJECTED_OUTPUT`, `COMPLETED`, `ORPHANED`.

Flow: `PLANNING → AWAITING_APPROVAL (gate A) → QUEUED → RUNNING → OUTPUT_VALIDATING → AWAITING_REVIEW (gate B) → COMPLETED`.

Code generation happens after gate A, inside `QUEUED`. Gate A approves the plan and limits, not the generated code. The generated code is shown read-only on the task page, with its SHA-256.

Invalid transitions return `409 INVALID_STATE`.

## 5. SSE events

`GET /api/agent/tasks/{id}/events` returns `text/event-stream`. Each event has a named type and JSON data:

```
event: state
data: {"task_id":"uuid","state":"RUNNING","at":"2026-11-05T10:03:00Z"}

event: log
data: {"task_id":"uuid","stream":"stdout","line":"Profiling dataset...","at":"..."}

event: gate
data: {"task_id":"uuid","gate":"A","status":"waiting"}

event: end
data: {"task_id":"uuid","state":"COMPLETED"}
```

A heartbeat comment (`: keep-alive`) is sent every 15 seconds. The stream closes after `end`. Clients reconnect with the same URL if the connection drops, and the server replays the current state first.

## 6. Sandbox interface (Python)

File: `backend/app/sandbox/base.py`. Owned by the sandbox implementer. Consumed by the backend.

```python
from dataclasses import dataclass, field
from typing import Protocol

@dataclass(frozen=True)
class ArtifactFile:
    name: str           # server-validated, e.g. "chart.png"
    path: str           # absolute path on the host, inside the data dir
    sha256: str
    size_bytes: int

@dataclass
class SandboxResult:
    task_id: str
    state: str          # "COMPLETED" | "FAILED_SANDBOX" | "TIMED_OUT"
    runner: str         # "docker" | "local"
    exit_code: int | None
    duration_ms: int
    timed_out: bool
    oom_killed: bool
    container_id: str | None
    stdout: str         # truncated to 64 KB by the runner
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    code_sha256: str
    artifacts: list[ArtifactFile] = field(default_factory=list)

class SandboxRunner(Protocol):
    name: str
    max_concurrent: int

    async def run(self, task_id: str, script: str,
                  inputs: dict[str, bytes], timeout_s: int) -> SandboxResult: ...

    async def cancel(self, task_id: str) -> None: ...

    async def sweep_orphans(self) -> int: ...      # returns number removed

    async def running_count(self) -> int: ...
```

Rules:
- `inputs` maps file name to bytes. The runner writes them into `/workspace` before execution. Only the names listed in the plan are accepted.
- The script is always named `task.py`.
- The runner collects only files in `/workspace/out/` as artifacts. Files over the size limit in SDD §17.2 are rejected.
- `DockerSandboxRunner` implements the full §9.3 flag set. `LocalProcessRunner` is development only, refuses to run when `DCE_ENV=production`, and sets `runner="local"` on every result.

## 7. Backend ↔ sandbox wiring

The backend selects a runner at startup from `DCE_SANDBOX_RUNNER` (`docker` or `local`). The task manager holds a semaphore sized to `max_concurrent`. Artifacts are copied into `DCE_DATA_DIR/artifacts/<task_id>/` with server-side names, and their hashes are recorded.

## 8. Inference interface

- `DCE_INFERENCE_MODE=mock` returns deterministic plans and scripts for the flood-analysis use case. This is the default for local development and tests.
- `DCE_INFERENCE_MODE=vultr` calls the OpenAI-compatible endpoint `DCE_INFERENCE_BASE_URL` (default `https://api.vultrinference.com/v1`) using `DCE_VULTR_INFERENCE_KEY` and `DCE_INFERENCE_MODEL`. The key is never logged or sent to the sandbox.
- Model output is validated against the plan schema above. Anything that fails validation becomes `FAILED_PLANNING`.

## 9. Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DCE_ENV` | `development` | `production` disables the local runner |
| `DCE_DATA_DIR` | `./data` | Uploads, artifacts, SQLite file |
| `DCE_DATABASE_PATH` | `./data/dce.sqlite3` | |
| `DCE_SERVE_FRONTEND` | `true` locally, `false` in production | When true, FastAPI serves `frontend/` at `/` |
| `DCE_FRONTEND_DIR` | `../frontend` | |
| `DCE_INFERENCE_MODE` | `mock` | `mock` or `vultr` |
| `DCE_INFERENCE_BASE_URL` | `https://api.vultrinference.com/v1` | |
| `DCE_INFERENCE_MODEL` | (empty) | Must come from the Vultr model list when mode is `vultr` |
| `DCE_VULTR_INFERENCE_KEY` | (empty) | Secret. Never committed |
| `DCE_SANDBOX_RUNNER` | `local` | `docker` in production |
| `DCE_SANDBOX_IMAGE` | `dce-worker:local` | Pinned digest in production |
| `DCE_SANDBOX_MAX_CONCURRENT` | `1` | 2 requires a 4 vCPU VM |
| `DCE_SANDBOX_TIMEOUT_S` | `30` | Hard limit |
| `DCE_SANDBOX_MEMORY_MB` | `512` | |
| `DCE_SANDBOX_PIDS` | `64` | |
| `DCE_COOKIE_SECURE` | `false` | `true` in production |
| `DCE_QUOTA_TASKS_PER_DAY` | `20` | |
| `DCE_CORS_ORIGINS` | `http://localhost:8000` | Development only |
| `DCE_TRUSTED_PROXIES` | `127.0.0.1` | Only these peers may set `X-Forwarded-For`. In production, Caddy on the VM is the single trusted proxy. Rate limits use the first untrusted address |
| `DCE_SESSION_SECRET` | (none) | Secret for signing session identifiers if the backend uses signed cookies. Never committed |
| `DCE_SEED_PASSWORD` | (none) | Required by `python -m app.seed`. Never committed |

## 10. Seed accounts (development and demo)

Created by `python -m app.seed` with password from `DCE_SEED_PASSWORD`:

| Username | Role |
|---|---|
| `admin` | Admin |
| `analyst` | Analyst |
| `reviewer` | Reviewer |
| `approver` | Approver |

## 12. Clarifications (v1.6.1, resolving the frontend review)

These rules are binding and extend the sections above.

**Request bodies (JSON unless noted)**
- Login: `{"username": "...", "password": "..."}`.
- Dataset upload: multipart, field `file` (required), field `name` (optional text).
- Agent task create: `{"instruction": "...", "dataset_id": "uuid", "requested_outputs": ["affected_areas", "blocked_roads", "resource_requirements", "situation_report"]}`. Each output name must be one of these four values, otherwise `400 VALIDATION_FAILED`. Output names map to the artifact allowlist in §6 of the sandbox.
- Gate decision: `{"gate": "A" | "B", "decision": "approve" | "reject", "note": "optional, max 500 chars"}`.

**Lists are bare JSON arrays.** Paginated lists (`/api/audit`) return `{"items": [...], "next_offset": number | null}` instead.

**Full incident rows for the map and chart.** The preview in a dataset is at most 5 rows, so it cannot show all incidents. Add:
- `GET /api/datasets/{id}/rows?limit=500&offset=0` (Viewer+, dataset must be APPROVED for non-owners) returns `{"items": [...], "next_offset": number | null, "total": number}`. Maximum `limit` is 1000. Values are the parsed CSV cells; empty cells are `null`. Coordinates are only plotted when both `lat` and `lon` are non-null, and nothing is invented.

**Audit verify response:** `{"valid": true | false, "checked": number, "first_bad_id": number | null}`.

**summary.json schema (written by the sandbox plan, consumed by the UI):**
```json
{
  "dataset_rows": 40,
  "flooded_districts": [{"district": "Kemang", "incidents": 3, "flooded_incidents": 2}],
  "blocked_roads": 9,
  "affected_population": {"sum": 12345, "unknown_rows": 4},
  "data_class": "SIMULATED_FACT"
}
```
Missing values are reported as unknown, never as zero.

**Gate permissions**
- Gate A (execution plan): role `Approver` or `Admin`, and never the owner of the task.
- Gate B (report release): role `Reviewer`, `Approver`, or `Admin`, and never the owner.
- Gate decisions are recorded in `approvals` with the approver's role.

**Cancel:** allowed in `QUEUED`, `RUNNING`, `AWAITING_APPROVAL`, `AWAITING_REVIEW`. Terminal states return `409 INVALID_STATE`. Owner or Admin only.

**Mock inference output names:** the mock planner only produces the four requested-output names above, plus the artifact names `summary.json`, `situation_report.md`, `chart.png`, `affected_areas.csv`, `blocked_roads.csv`.

**Generated code visibility:** the API exposes `code_sha256` only. The script is not an artifact. A reviewer who needs it reads it from the task's audit detail, which stores the hash only. Showing the full script in the UI is out of scope for v1.6.

**Chart.js:** CDN `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js`. Leaflet 1.9.4 from unpkg. SRI hashes are added at deployment time.

## 11. Frontend ↔ backend rules

- The frontend uses only `/api/*`. It never calls inference or Docker.
- It renders `data_class` labels on every result (SDD §16.3).
- It shows gate A and gate B controls to the correct role only, and hides controls the user cannot use.
- It keeps SSE connections open only while the task page is visible, and reconnects on failure.
