# Security

This document covers the security model of Disaster Commander Edge: the sandbox boundary, the threat model, secret handling and rotation, and open items. The normative source is SDD sections 9, 20, and 21.

## 1. Security objective (SDD 9.1)

Agent-generated code runs outside the main application process. The sandbox is disposable. The application host stays protected even when generated code is malicious or wrong, and even when the orchestration layer is compromised to the degree this design can contain.

Docker containers alone are not treated as an absolute boundary against every hostile workload (SDD 9.3). The stronger option is gVisor or a disposable VM (ADR-010), which is not implemented yet.

## 2. Sandbox boundary

- **Trusted domain:** FastAPI, orchestrator, task manager, database, secret store, artifact manager.
- **Dispatcher:** runs unprivileged. Docker access is through rootless Docker (preferred) or a restricted socket proxy (fallback). See `deployment/vultr/rootless-docker.md`.
- **Controlled input:** only approved files, size-checked, copied in with `docker cp` or stdin. No bind mounts.
- **Untrusted domain:** a disposable worker with `--network none`, `--read-only`, a tmpfs `/workspace`, `--cap-drop ALL`, `no-new-privileges`, a seccomp profile, user `65534`, 1 CPU, 512 MB memory with swap disabled, and 64 PIDs.
- **Controlled output:** only allowlisted file names and types (`csv`, `json`, `png`, `pdf`, `md`, `py`, `log`), with a size limit. Output is hashed.

The worker never receives the Docker socket, the proxy address, the database, or any secret.

## 3. Containment controls

| Official requirement (SDD 2.4) | Control |
| --- | --- |
| Execution never touches the host or app runtime | Separate container, no bind mounts, read-only root, dispatcher isolated |
| No API keys or credentials inside the sandbox | Environment allowlist only; keys are never passed (SDD 9.5) |
| Time and memory caps on every run | 30 s timeout, 512 MB, 64 PIDs, 1 CPU, orphan sweeper |
| Environment reset or destroyed after each task | `docker rm` in a `finally` block; label-based sweeper |
| Demo shows a containment moment | Canonical tests T01 to T12, see `scripts/containment-checklist.md` |

## 4. Threat model (SDD 9.9)

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Generated code escapes the container | seccomp, cap-drop, no-new-privileges, non-root user, rootless Docker | Kernel exploit. Mitigation option: gVisor or VM (ADR-010) |
| Generated code exfiltrates data | `--network none`; no secrets in the environment | Exfiltration inside an output artifact. Mitigated by output review gate B |
| Generated code exhausts host resources | cgroup CPU, memory, and PID limits; timeout; concurrency cap | Shared-kernel side effects under extreme load |
| Compromised dispatcher controls Docker | Unprivileged user; rootless daemon, or proxy allowlist (SDD 9.3a) | Proxy vulnerability. The proxy allowlist is coarser than the spec (see section 7) |
| Prompt injection in a dataset causes an unsafe plan | Plan validation against the tool registry and schema (SDD 8.5); gate A | A plausible but wrong plan, caught by review |
| Abuse of the public agent endpoint | Authentication, per-user quota, daily global cap (SDD 20.6) | An authenticated user within quota |
| Orphaned containers after a crash | Startup reconciliation and orphan sweeper (SDD 9.2, 21.3) | Brief window before the sweep |

Additional controls for the public deployment:

- **TLS and headers.** Caddy issues certificates automatically. Responses carry HSTS, `X-Content-Type-Options: nosniff`, a strict `Referrer-Policy`, `X-Frame-Options: DENY`, and a Content-Security-Policy with no inline script and no `unsafe-eval`.
- **Host firewall.** UFW allows SSH only from the admin IP. HTTP and HTTPS are public. Everything else is denied.
- **Body limits.** Dataset uploads are capped at 12 MB at the proxy. The application limit is 10 MB (`docs/api.md` section 3).
- **Logs.** The Caddy access log strips query strings.
- **Accounts.** The backend runs as uid 10001. The `dce` and `dce-sandbox` users have no sudo rights and are not in the `docker` group. Session cookies are `HttpOnly; SameSite=Strict; Secure` in production.
- **Updates.** Unattended security upgrades are enabled. fail2ban protects SSH.

## 5. Secrets inventory

| Secret | Where it lives | Who can read it | Never in |
| --- | --- | --- | --- |
| `DCE_VULTR_INFERENCE_KEY` | VM `/srv/dce/app/.env` (mode 0640, group `dce`) | backend container (env) | repo, logs, sandbox, audit, browser |
| `DCE_SEED_PASSWORD` | Shell for one run only; removed from `.env` after seeding | operator | repo, disk, logs |
| Seed account passwords | Hashed in the database | backend | plain text anywhere |
| Vultr account and API access | Vultr console, 2FA on | owner | repo, VM |
| SSH private keys | Admin laptop | admin | VM, repo |
| Session cookie | Browser (`dce_session`) | user | URLs, logs |

`.env` is listed in `.gitignore`. `.env.example` contains placeholders only.

## 6. Secret rotation procedure

Rotate on any suspicion of exposure, after staff changes, and on a fixed schedule (for example every 90 days during the demo period).

**Inference key (`DCE_VULTR_INFERENCE_KEY`)**

1. In the Vultr console, create a new inference key. Leave the old key active for now.
2. On the VM, edit `/srv/dce/app/.env` in place and replace the value. Do not paste it into a shell command, so it stays out of shell history.
3. Restart the backend so it reads the new value: `cd /srv/dce/app && docker compose -f deployment/docker-compose.yml --env-file .env up -d api`.
4. Check `GET /api/dashboard/summary` (`inference.mode` is `vultr`) and run one agent task.
5. Revoke the old key in the Vultr console.
6. Record the rotation date in the operator log (not in the repo).

**Operator password reset (for a user who cannot sign in)**

Use this when no Admin can sign in and the account owner has lost the password. It needs shell access to the VM, so only the operator can run it. Any user who can still sign in changes their own password through the app (`POST /api/auth/password`).

1. Run it from the API container, with `-it` so the prompt works: `cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env exec -it api python -m app.reset_password <username>`
2. Type the new password twice when prompted. It must meet the password policy (at least 12 characters) and differ from the current one. Nothing is printed back.
3. The command replaces the hash, revokes every session of that user, and writes `auth.password_reset_by_operator` (actor `operator`) to the audit log. The password itself is never logged.
4. Record the date and the username in the operator log (not in the repo).

Add `--role ROLE` to set the role as well. ROLE is one of `Viewer`, `Analyst`, `Reviewer`, `Approver`, or `Admin`.

- If the username does not exist, `--role` creates the account with that role (audit `auth.user_created_by_operator`).
- If it exists, `--role` changes its role (audit `admin.user_role_changed`). The last active Admin cannot be demoted, and a refused run changes nothing.
- Without `--role`, a missing username is refused.

**Seed passwords**

1. Export the new value in your shell with `read -rs DCE_SEED_PASSWORD; export DCE_SEED_PASSWORD`.
2. Run `docker compose -f deployment/docker-compose.yml --env-file .env run --rm -e DCE_SEED_PASSWORD api python -m app.seed`. Confirm in `app/seed.py` how existing accounts are handled before relying on it to change passwords (open item).
3. `unset DCE_SEED_PASSWORD`. Confirm it is not in `.env`.
4. Sign out all sessions if the backend supports it (open item, see section 7).

**Rotating the sandbox image**

Build a new worker image, record its digest with `deployment/vultr/build-worker-image.sh`, update `DCE_SANDBOX_IMAGE` in `.env`, and restart the backend. Keep the previous digest for rollback. Run the containment checklist (T01 to T12) again before the demo.

**SSH and host keys**

Add the new admin key to `~/.ssh/authorized_keys` for the admin user. Test it in a second session. Then remove the old key. Never disable password login before key login is confirmed in a second session.

**Compromise response (summary)**

1. Revoke the inference key in the Vultr console.
2. Stop the backend: `docker compose ... stop api`.
3. Take a backup copy of the database for forensics (`scripts/backup.sh`).
4. Rotate all secrets in section 5.
5. Check the audit chain (`POST /api/audit/verify`, Admin role).
6. Restore from a known-good backup if the chain fails (`docs/deployment.md`, restore procedure).

## 7. Open items and known gaps

These are recorded so they are not forgotten. None of them is hidden by the deployment files.

1. **Proxy granularity.** `tecnativa/docker-socket-proxy` filters by API section. `CONTAINERS=1` allows all container endpoints. SDD 9.3a also requires a path allowlist and rejection of `Privileged`, `Binds`, `CapAdd`, a non-`none` `NetworkMode`, and non-default `PidMode` or `IpcMode`. Those checks must live in the dispatcher. Until they exist, the proxy path is weaker than rootless Docker, and this is recorded as a residual risk.
2. **Dispatcher IPC.** The rootless design runs the dispatcher as `dce-sandbox`, but the protocol between the backend and that dispatcher is not defined in `docs/api.md` or the SDD.
3. **Client IP behind Caddy.** Implemented in v1.6.2: `X-Forwarded-For` is read only when the direct peer is listed in `DCE_TRUSTED_PROXIES` (`docs/api.md` section 9). The default is empty, so an unset deployment ignores the header. Production must set the Caddy-facing address (the Docker bridge gateway as the backend sees it). Until that is set, every client behind Caddy shares one login rate-limit bucket, which is a fail-closed rather than a bypass. The deployment files are not yet updated for this.
4. **Session secret.** `docs/api.md` section 9 has no session-signing secret variable. If sessions are signed, the variable must be added to the contract and to `.env.example`.
5. **Login and upload field names.** `docs/api.md` does not define the login body or the upload form field name. The smoke test assumes `{"username","password"}` and a multipart field named `file`.
6. **Frontend CSP: `'unsafe-inline'` remains in `style-src` (both `backend/app/middleware.py` and `deployment/Caddyfile`).** Removing it was attempted and blocked. `frontend/js/dom.js` sets a string `style` prop with `node.setAttribute('style', ...)`, and 57 call sites in `frontend/js/` pass string styles (for example `style: '--i:1'` and `style: 'justify-content:space-between'`). Under `style-src` without `'unsafe-inline'`, the browser refuses `setAttribute('style')` and inline style attributes. Object-form styles (`Object.assign(node.style, ...)`, CSSOM) are allowed, and only one call site uses that form. The fix is to route all string styles through CSSOM (or a stylesheet class), then remove `'unsafe-inline'` from both files together. The two CSP strings must stay byte-identical.7. **Image digests.** The base images (`python:3.12-slim`, `tecnativa/docker-socket-proxy`) are pinned by tag. Pin them by digest before submission, and record the digest here.
8. **Key-only SSH.** Password login should be disabled manually (`docs/deployment.md`, step 6). The setup script does not change SSH configuration.
9. **Docker group on admin.** The admin account may be in the `docker` group, which is root-equivalent. This is acceptable only because admin is trusted. App users are never added.
