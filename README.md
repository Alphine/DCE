# Disaster Commander Edge (DCE)

Disaster Commander Edge is a decision-support system for disaster operators. Operators upload incident data, such as flood reports from a district, and DCE turns it into profiles, rules, graphs, simulations, and situation reports. Deterministic engines produce the results. An AI agent plans the analysis, but it never runs its own code on the application host.

The product is built for operators who need a clear, auditable picture quickly, and who need to know which parts of a result are simulated, which are rule-based, and who approved what. Every result carries a data-class label, and the human approval gates are part of the workflow, not an afterthought.

## Blast Radius Zero

Agent-generated code is untrusted. DCE runs each task in a disposable, locked-down Docker worker with no network, a read-only root filesystem, a 30-second timeout, a 512 MB memory cap, a 64-process limit, no secrets in its environment, and no access to the Docker API. The container is destroyed after every run, and an orphan sweeper removes leftovers. Every run leaves evidence: the container configuration, exit code, resource usage, artifact hashes, and audit record IDs. A hostile test suite (T01 to T12) checks each control, and the host stays responsive while it runs.

The demo shows the containment moments live: an infinite loop stopped at 30 seconds, and a memory bomb killed by the kernel while the API keeps answering health checks.

<!-- Screenshot placeholder: replace with docs/screenshots/dashboard.png once captured. -->
> **[Screenshot placeholder]** Task Execution Monitor and Artifact Viewer.

## Quick start (local development)

Requirements: Python 3.12 or newer. Docker is optional. Without it, the sandbox runs in `local` mode, which is NOT isolated and is for development only.

**Windows (PowerShell), primary path:**

```powershell
.\scripts\dev.ps1                 # creates backend\.venv, installs requirements, starts the server
.\scripts\dev.ps1 -SkipInstall    # restart without reinstalling
```

If PowerShell blocks the script: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1`.

To seed the demo accounts, set the password for the current shell only. It is never written to disk:

```powershell
$env:DCE_SEED_PASSWORD = '<a development password>'
.\scripts\dev.ps1
Remove-Item Env:DCE_SEED_PASSWORD
```

**macOS and Linux:**

```bash
./scripts/dev.sh                  # add --skip-install to skip pip
```

Open http://127.0.0.1:8000 when the server starts. To check the running server end to end, run the smoke test with the same seed password in your shell:

```bash
python scripts/smoke.py           # checks health, login, dashboard, and a sample upload
```

Sample data: `datasets/samples/flood_incidents_sample.csv` is synthetic (see `datasets/samples/README.md`). Do not use it for operational decisions.

## Architecture

```
  Browser (HTML / CSS / JS)
        |  HTTPS, one origin: commander.basyid.dev
        v
  Caddy (automatic TLS) ----------------- /  -> static frontend
        |  /api/*
        v
  FastAPI backend (auth, quota, task state machine, SSE)
        |                          |
        |  deterministic engines   |  agent planner
        |  rules, graph, sim,      |  Vultr Serverless Inference
        |  geospatial              |  (api.vultrinference.com/v1)
        |                          |
        |                  plan validated against schema
        |                          |  gate A (human)
        |                          v
        |              sandbox dispatcher (unprivileged)
        |                          |
        |                          v
        |              disposable Docker worker
        |                (no network, read-only, capped,
        |                 destroyed after each run)
        |                          |  allowlisted outputs
        |                          v
        |              output validator, gate B (human)
        v
  SQLite (WAL) + artifacts + hash-chained audit log
```

Vultr services used: a Vultr Cloud Compute VM (Ubuntu LTS) hosts the whole stack. Vultr Serverless Inference runs every agent LLM call. No GPUs are used.

More detail: `docs/architecture.md`. Threat model and secret rotation: `docs/security.md`.

## Folder structure

```
disaster-commander-edge/
├── backend/           FastAPI app, agent, sandbox dispatcher, tests (pytest)
├── frontend/          Static web app served by Caddy
├── sandbox/           Worker image: Dockerfile, worker.py, seccomp profile
├── datasets/
│   └── samples/       Synthetic sample data (flagged as synthetic)
├── deployment/
│   ├── Caddyfile                   Production reverse proxy and headers
│   ├── docker-compose.yml          API and restricted Docker proxy
│   ├── Dockerfile.backend          API image
│   └── vultr/                      VM bootstrap, worker build, rootless Docker guide
├── docs/              Architecture, security, deployment, API contract
├── scripts/           dev.ps1, dev.sh, smoke.py, backup.sh, restore.sh, containment checklist
├── .env.example       Configuration names and placeholders (no secrets)
├── LICENSE            MIT
└── README.md
```

## Configuration

All settings are environment variables. The full list, with defaults and notes, is in `docs/api.md` section 9. Copy `.env.example` to `.env` for local work. Never commit `.env`. Production secrets live only on the VM, in a file with mode 0640 (see `docs/deployment.md`).

## Testing

```bash
cd backend
pytest                            # unit, security, and resilience suites
```

Windows, from the backend folder with the virtual environment active: `.venv\Scripts\activate` and then `pytest`.

The containment tests (T01 to T12) and their evidence commands are in `scripts/containment-checklist.md`.

## Deployment

The live path is `https://commander.basyid.dev`, served from one Vultr VM. Step-by-step instructions, from an empty VM to a live site, including DNS, Caddy, the firewall, seeding, the worker image digest, the smoke test, and backup and restore, are in `docs/deployment.md`. The sandbox runtime options (rootless Docker or the fallback socket proxy) are in `deployment/vultr/rootless-docker.md`.

## Official challenge deliverables

Vultr: Agent Rush, Challenge 1 (Blast Radius Zero). Checklist from SDD section 2.4:

Mandatory platform requirements

- [ ] Vultr Cloud Compute VM hosts the backend, and the web app is deployed on Vultr
- [ ] Vultr Serverless Inference handles all agent LLM calls (`api.vultrinference.com/v1`)
- [x] No Vultr GPUs used
- [ ] Team of 1 to 6 members, registered on lablab.ai

Containment requirements

- [ ] Execution never touches the host or app runtime (SDD 9.1, 9.3, 9.6)
- [ ] No API keys or credentials inside the sandbox (SDD 9.5)
- [ ] Time and memory caps on every run (SDD 9.4)
- [ ] Environment reset or destroyed after each task (SDD 9.2, 23.2)
- [ ] Demo video shows at least one containment moment (SDD 23.4)

Required deliverables

- [ ] Public GitHub repository, MIT-licensed, with setup docs and this README
- [ ] Vultr VM backend and public demo URL
- [ ] Recorded demo video with a containment moment
- [ ] Slide presentation covering architecture and containment evidence
- [ ] Cover image, title, short and long descriptions, and tags for the lablab.ai listing
- [ ] Official lablab.ai submission

The official submission deadline is not published on the event page. Confirm it with the organizers.

## License

MIT License. Copyright (c) 2026 Fakhrurrozi Basyid. See `LICENSE`.

The copyright holder name is taken from the SDD. It can be changed in `LICENSE` and in this README if the legal entity differs.

Built by Kawalight Studio for the Vultr Agent Rush hackathon.
