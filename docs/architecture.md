# Architecture

Disaster Commander Edge (DCE) is a disaster-response decision-support system for operators. It combines deterministic analysis with an agent that plans work. The agent's generated code always runs in a disposable sandbox, and a human approves each gate. This document summarizes the design. The full specification is the SDD (v1.6). The API contract is in `docs/api.md`.

## Design principles

- **Hybrid intelligence (ADR-001).** Deterministic engines (rules, graph, simulation) produce the results. The LLM only plans. Its output is validated against a schema and a tool registry before anything runs.
- **Separate execution plane (ADR-002).** Code written by the agent never runs inside the application process.
- **Human in command (ADR-008).** Gate A approves the plan and limits. Gate B approves the outputs before they are published. Nobody approves their own work.
- **Single origin (ADR-005, revised in v1.6).** The browser talks to one host, `commander.basyid.dev`, over HTTPS. Caddy serves the frontend and proxies `/api/*`.

## Deployment topology

```
                              INTERNET
                                 |
                  commander.basyid.dev  (A record -> Vultr VM IPv4)
                                 |
        +------------------------+------------------------+
        |  Vultr Cloud Compute VM (Ubuntu LTS, 2 vCPU / 4 GB)
        |                                                 |
        |  Caddy :443 (automatic HTTPS)                   |
        |    /        -> /srv/dce/frontend (static files) |
        |    /api/*   -> 127.0.0.1:8000                   |
        |                    |                            |
        |          +---------+----------+                 |
        |          | api (FastAPI)      |  127.0.0.1:8000 |
        |          |  auth, quota, SSE  |  (published on  |
        |          |  task state machine|   loopback only)|
        |          |  inference client  |                 |
        |          |  sandbox dispatcher|                 |
        |          +--+-----------+-----+                 |
        |             |           |                       |
        |   dce_internal net  dce_egress net              |
        |             |           |                       |
        |   docker-socket-proxy   +--> Vultr Serverless   |
        |   (only mounts socket)        Inference         |
        |             |                 api.vultrinference.com/v1
        |             v                                   |
        |   Docker daemon -> disposable worker containers |
        |     --network none, --read-only, tmpfs /workspace
        |     seccomp, cap-drop ALL, 1 CPU, 512 MB, 64 PIDs
        |                                                 |
        |   SQLite (WAL) in /srv/dce/data                 |
        |   Nightly backup -> /srv/dce/backups            |
        +-------------------------------------------------+
```

Preferred sandbox runtime: rootless Docker under the `dce-sandbox` user, with the dispatcher running as that user (SDD 9.3a, `deployment/vultr/rootless-docker.md`). The socket proxy shown above is the fallback path, and it is weaker. See `docs/security.md`.

## Components

| Component | Location | Role |
| --- | --- | --- |
| Frontend | `frontend/` (served from `/srv/dce/frontend`) | HTML, CSS, JS. Uses only `/api/*`. Never calls inference or Docker. |
| API | `backend/app/api/` | Endpoints in `docs/api.md` section 2. JSON in and out, SSE for task events. |
| Auth and quotas | `backend/app/auth/` | Sessions in `dce_session`, roles, rate limits, daily task quota. |
| Agent | `backend/app/agent/` | Orchestrator, planner, task manager (state machine), inference client, tool registry, output validator. |
| Sandbox | `backend/app/sandbox/`, `sandbox/` | Dispatcher, Docker runtime, resource limits, lifecycle, orphan sweeper, flag verification. Worker image in `sandbox/`. |
| Intelligence | `backend/app/intelligence/`, `expert_system/`, `knowledge_graph/`, `geospatial/`, `simulation/` | Deterministic engines. Results carry a `data_class` label. |
| Database | `backend/app/database/` | SQLite in WAL mode. Numbered migrations. |
| Artifacts | `backend/app/artifacts/` | Server-named files under `DCE_DATA_DIR/artifacts/<task_id>/`, with SHA-256 hashes. |
| Audit | `backend/app/audit/` | Hash-chained records. Stores IDs and hashes, never secrets or raw data. |
| Reverse proxy | `deployment/Caddyfile` | TLS, static files, body limits, security headers, access log without query strings. |
| Containers | `deployment/docker-compose.yml`, `deployment/Dockerfile.backend` | API container and the restricted Docker proxy. |

## Task lifecycle

```
PLANNING -> AWAITING_APPROVAL (gate A) -> QUEUED -> RUNNING -> OUTPUT_VALIDATING
         -> AWAITING_REVIEW (gate B) -> COMPLETED
```

Other terminal states are `FAILED_PLANNING`, `REJECTED`, `CANCELLED`, `TIMED_OUT`, `FAILED_SANDBOX`, `REJECTED_OUTPUT`, and `ORPHANED`. Code is generated after gate A, inside `QUEUED`. Gate A approves the plan and resource limits, not the code. The generated code is shown read-only, with its SHA-256 hash.

## Sandbox lifecycle (SDD 9.2)

1. Slot acquired (concurrency gate, `DCE_SANDBOX_MAX_CONCURRENT`).
2. Resource validation.
3. Container created with labels `dce.task` and `dce.created`.
4. Security configuration verified with `docker inspect`. If verification fails, the container is never started.
5. Approved inputs copied in. No bind mounts, no environment secrets.
6. Execution under a hard timeout (30 s).
7. Output collection and validation.
8. Artifact export.
9. Container destroyed in a `finally` block, always.
10. Audit record finalized.

An orphan sweeper runs every 60 seconds and removes labelled containers older than the timeout plus 30 seconds. Startup reconciliation marks interrupted tasks `ORPHANED` (SDD 21.3).

## Data classes

Every result shows its class in the UI: `SIMULATED_FACT`, and the other labels defined in SDD 16.3. The sample dataset is synthetic. See `datasets/samples/README.md`.

## Inference

All agent LLM calls go to Vultr Serverless Inference (`DCE_INFERENCE_BASE_URL`, default `https://api.vultrinference.com/v1`). The API key stays in the backend. It is never logged, never shown to the browser, and never passed to the sandbox. There is no other LLM provider in the codebase (SDD 23.4). `DCE_INFERENCE_MODE=mock` is the default for development and tests.

## Not in scope for the hackathon

- GPU inference (not available for this event, and not needed; SDD 5.6).
- Multi-node deployment, PostgreSQL, Object Storage (later phases, SDD 5.3).
- Local llama.cpp offline mode (future, SDD 6.2).
