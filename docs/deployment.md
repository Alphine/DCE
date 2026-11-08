# Deployment

This guide takes an empty Vultr VM to a live site at `https://commander.basyid.dev`. It covers the DNS record, Caddy, the firewall, the sandbox runtime, seeding, the worker image, the smoke test, backups, and restore. Follow the steps in order. The design is in `docs/architecture.md`, and the security rules are in `docs/security.md`.

Placeholders in angle brackets (for example `<VM_IPV4>`) are values you supply. Never commit real values.

## 0. What you need

- A Vultr account with billing set up, and the lablab.ai credits redeemed (SDD Appendix E).
- A Vultr Serverless Inference API key and a model ID from the Vultr model list.
- Control of the `basyid.dev` DNS zone.
- An SSH key pair on your admin laptop.
- Your admin laptop's public IPv4 address (for the SSH allowlist). Check it with `curl -4 ifconfig.me`.
- A container registry you can push to (for the worker image digest).
- The repository URL: `<REPO_URL>`.

## Go-live checklist, step by step

This is the ordered runbook. Sections 1 to 16 below give the detail and the reasons. Run the commands on the VM as the admin user unless a block says otherwise. Replace each `<...>` placeholder. Never type a secret into a shell command or paste it into chat.

Three ordering rules: the DNS record exists before the first Caddy start (G3 to G4), the firewall is up before the public site is live (G10 to G11), and `.env` exists before the first `docker compose up` (G17 to G18).

Known gaps to read before you start (details in `docs/security.md`, section 7):

- **Rootless Docker is not wired.** `docker-compose.yml` runs the socket-proxy path. Rootless needs the dispatcher IPC, which does not exist yet.
- **Login rate limit shares one bucket.** The backend keys on the peer address, which is the Docker gateway behind Caddy. `DCE_TRUSTED_PROXIES` is in `docs/api.md` but not implemented.
- **Passwords can be changed.** Users change their own with `POST /api/auth/password`. An operator resets a locked-out user with `python -m app.reset_password <username>` (see `docs/security.md`, section 6). `app.seed` still skips existing accounts.
- **Do not copy the laptop database to the VM.** `backend/data/dce.sqlite3` is a development database. The VM must start with an empty `/srv/dce/data`.

### G1. Record your admin IPv4 (on your laptop)

```bash
curl -4 ifconfig.me
```

Save the output as `<YOUR_ADMIN_IPV4>`. A wrong value locks you out of SSH.

### G2. Create the VM (Vultr console, manual)

Ubuntu LTS, 2 vCPU, 4 GB RAM, 80 GB SSD, your SSH public key only. Record the public IPv4 as `<VM_IPV4>`. No command runs here.

### G3. Create the DNS A record (basyid.dev zone, manual)

Name `commander`, type `A`, value `<VM_IPV4>`, TTL 300. Do this before G4 and before G28.

### G4. Verify DNS from your laptop

```bash
dig +short commander.basyid.dev
```

Expect `<VM_IPV4>`. On Windows without `dig`, run `nslookup commander.basyid.dev`. Do not continue until it matches, because Let's Encrypt fails otherwise and repeated failures hit rate limits.

### G5. First SSH login (default provider user)

```bash
ssh -i ~/.ssh/<KEY_FILE> <PROVIDER_DEFAULT_USER>@<VM_IPV4>
```

### G6. Install git

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y git
```

### G7. Create the admin user

```bash
sudo adduser --gecos "" <ADMIN_USER>
```

Choose a strong password. It is used only for `sudo`.

```bash
sudo usermod -aG sudo <ADMIN_USER>
```

```bash
sudo install -d -m 0700 -o <ADMIN_USER> -g <ADMIN_USER> /home/<ADMIN_USER>/.ssh
```

```bash
sudo install -m 0600 -o <ADMIN_USER> -g <ADMIN_USER> /home/<PROVIDER_DEFAULT_USER>/.ssh/authorized_keys /home/<ADMIN_USER>/.ssh/authorized_keys
```

If the provider put the key under `/root/.ssh`, use that path instead.

### G8. Verify the admin login in a second terminal (keep the first one open)

On your laptop:

```bash
ssh -i ~/.ssh/<KEY_FILE> <ADMIN_USER>@<VM_IPV4>
```

Then, on the VM, confirm sudo works:

```bash
sudo -v
```

### G9. Create the code directory and clone the repo

```bash
sudo mkdir -p /srv/dce
```

```bash
sudo git clone <REPO_URL> /srv/dce/app
```

### G10. Run the VM bootstrap

```bash
cd /srv/dce/app && sudo ADMIN_IP=<YOUR_ADMIN_IPV4> DOMAIN=commander.basyid.dev bash deployment/vultr/setup-vm.sh
```

This installs Docker Engine, Caddy, fail2ban, and unattended upgrades. It creates the `dce` and `dce-sandbox` users and the `/srv/dce` tree, and it enables UFW. Keep the session open. If you connect from another IP, you will be cut off from SSH.

### G11. Check the firewall

```bash
sudo ufw status verbose
```

Expect `deny (incoming)`, `22/tcp ALLOW <YOUR_ADMIN_IPV4>`, `80/tcp ALLOW`, and `443/tcp ALLOW`. Nothing else.

### G12. Harden SSH (key only)

```bash
sudo tee /etc/ssh/sshd_config.d/10-dce-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
```

```bash
sudo sshd -t
```

```bash
sudo systemctl reload ssh
```

### G13. Verify key login and that password login is refused

On your laptop, in a new terminal:

```bash
ssh -i ~/.ssh/<KEY_FILE> <ADMIN_USER>@<VM_IPV4>
```

```bash
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password <ADMIN_USER>@<VM_IPV4>
```

The second command must fail with `Permission denied`. Close the old session only after the first command works.

### G14. Check fail2ban

```bash
sudo fail2ban-client status sshd
```

### G15. Choose the sandbox runtime (decision, record it in docs/security.md)

- **Path B (socket proxy, runs today):** `docker-compose.yml` already defines it. Nothing else to install.
- **Path A (rootless, preferred by SDD 9.3a):** follow `deployment/vultr/rootless-docker.md`, sections 1 to 3 and 5. Do not choose it for go-live until the dispatcher IPC exists (`docs/security.md`, section 7, item 2).

### G16. Install the worker seccomp profile on the host

```bash
sudo install -D -m 0644 -o root -g root /srv/dce/app/sandbox/seccomp/profile.json /srv/sandbox/seccomp/profile.json
```

```bash
sudo ls -l /srv/sandbox/seccomp/profile.json
```

The dispatcher passes this path to the Docker daemon, and `docker-compose.yml` mounts the same path into the api container.

### G17. Create `.env` from the template

```bash
cd /srv/dce/app && sudo install -m 0640 -o root -g dce .env.example .env
```

### G18. Edit `.env` (editor, not a shell command)

```bash
sudo nano /srv/dce/app/.env
```

Set these, and no others:

- `DCE_ENV=production`
- `DCE_SERVE_FRONTEND=false`
- `DCE_COOKIE_SECURE=true`
- `DCE_INFERENCE_MODE=vultr`
- `DCE_INFERENCE_MODEL=<model ID from the Vultr list>`
- `DCE_VULTR_INFERENCE_KEY=<a new key created in the Vultr console>`
- `DCE_SANDBOX_RUNNER=docker`
- `DCE_SANDBOX_IMAGE=<filled in at G22>`
- `DCE_SANDBOX_MAX_CONCURRENT=1`
- `DCE_SEED_PASSWORD=<a strong password, removed at G34>`

Do not reuse a key or password from the laptop.

### G19. Verify the `.env` mode and owner

```bash
ls -l /srv/dce/app/.env
```

Expect `-rw-r----- 1 root dce`.

### G20. Verify that `.env` is ignored by git

```bash
cd /srv/dce/app && git check-ignore -v .env
```

Expect a `.gitignore` match on the `.env` line.

### G21. Verify the data directory is empty

```bash
sudo ls -la /srv/dce/data
```

Expect no `dce.sqlite3`. The database is created on first start.

### G22. Build and record the worker image

```bash
sudo docker login <registry-host>
```

```bash
cd /srv/dce/app && sudo env DCE_WORKER_REGISTRY=<registry-host>/<namespace> bash deployment/vultr/build-worker-image.sh
```

```bash
sudo cat /srv/dce/app/deployment/vultr/worker-image.digest
```

Copy the `dce-worker@sha256:...` line into `DCE_SANDBOX_IMAGE` in `.env` (`sudo nano`). It must be a digest reference.

### G23. Check the worker runs as uid 65534 with the SDD 9.3 limits

```bash
sudo docker run --rm --entrypoint id --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --memory 512m --memory-swap 512m --pids-limit 64 "$(sudo cat /srv/dce/app/deployment/vultr/worker-image.digest)"
```

Expect `uid=65534`.

### G24. Deploy the frontend

```bash
sudo rsync -a --delete /srv/dce/app/frontend/ /srv/dce/frontend/
```

```bash
sudo chmod -R a+rX /srv/dce/frontend
```

### G25. Start the backend and the socket proxy

```bash
cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env up -d --build
```

### G26. Check the containers and the port binding

```bash
cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env ps
```

Expect `api` and `docker-socket-proxy` running. Only `127.0.0.1:8000` is published.

### G27. Check the backend on loopback

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expect `{"status":"ok"}`.

### G28. Install and validate the Caddyfile, then start Caddy

```bash
sudo install -m 0644 /srv/dce/app/deployment/Caddyfile /etc/caddy/Caddyfile
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

```bash
sudo systemctl restart caddy
```

### G29. Check certificate issuance

```bash
sudo journalctl -u caddy -n 100 --no-pager | grep -i -E "certificate obtained|error"
```

Expect `certificate obtained successfully`. On errors, check G4 (DNS) and G11 (ports 80 and 443) before restarting Caddy again.

### G30. Check the public site

```bash
curl -sI https://commander.basyid.dev/
```

Expect `HTTP/2 200`.

```bash
curl -s https://commander.basyid.dev/api/health
```

Expect `{"status":"ok"}`.

### G31. Verify the security headers

```bash
curl -sI https://commander.basyid.dev/ | grep -i -E "^(content-security-policy|strict-transport-security|x-frame-options|x-content-type-options|referrer-policy):"
```

```bash
curl -sI https://commander.basyid.dev/api/health | grep -i -E "^(content-security-policy|strict-transport-security|x-frame-options|referrer-policy|cache-control):"
```

The `content-security-policy` value must be identical on both responses and identical to the CSP in `backend/app/middleware.py`. `/api/health` must show `cache-control: no-store`. This check is not yet run against a live Caddy.

### G32. Seed the four accounts

```bash
read -rs DCE_SEED_PASSWORD && export DCE_SEED_PASSWORD
```

```bash
cd /srv/dce/app && sudo --preserve-env=DCE_SEED_PASSWORD docker compose -f deployment/docker-compose.yml --env-file .env run --rm -e DCE_SEED_PASSWORD api python -m app.seed
```

```bash
unset DCE_SEED_PASSWORD
```

Expect `created` for each account. `exists` means the accounts were already seeded.

### G33. Run the smoke test from your laptop

Use the same password value you typed at G32. The smoke test writes test data (uploads and tasks) to production, and it counts against the daily quota.

```bash
read -rs DCE_SEED_PASSWORD && export DCE_SEED_PASSWORD
```

```bash
cd "<path-to-your-local-repo>" && python scripts/smoke.py --base-url https://commander.basyid.dev
```

```bash
unset DCE_SEED_PASSWORD
```

Every row must show `PASS`. Keep the output as evidence.

### G34. Remove the seed password from `.env` and recreate the API

Remove the variable from the file, then recreate `api` so the running container drops it too.

```bash
cd /srv/dce/app && sudo sed -i '/^DCE_SEED_PASSWORD=/d' .env
```

```bash
cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env up -d api
```

```bash
sudo docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' dce-api-1 | grep -c '^DCE_SEED_PASSWORD='
```

Expect `0`. The inspect command prints no other secrets.

### G35. Demo password (decision, not a command)

`python -m app.seed` skips accounts that already exist, so it never changes a password. Signed-in users change their own password through `POST /api/auth/password`. If an account is locked out, the operator runs `python -m app.reset_password <username>` (`docs/security.md`, section 6). Keep at least two active Admins, so that one forgotten password does not lock everyone out. Make every password strong and unique.

### G36. Set up the nightly backup

Test once, by hand, as the `dce` user:

```bash
sudo -u dce env DCE_DATABASE_PATH=/srv/dce/data/dce.sqlite3 DCE_BACKUP_DIR=/srv/dce/backups /bin/bash /srv/dce/app/scripts/backup.sh
```

```bash
sudo ls -l /srv/dce/backups
```

The cron job runs as `dce`, so `dce` must own its log file:

```bash
sudo install -m 0640 -o dce -g dce /dev/null /var/log/dce-backup.log
```

```bash
sudo tee /etc/cron.d/dce-backup >/dev/null <<'EOF'
SHELL=/bin/bash
17 2 * * * dce DCE_DATABASE_PATH=/srv/dce/data/dce.sqlite3 DCE_BACKUP_DIR=/srv/dce/backups /bin/bash /srv/dce/app/scripts/backup.sh >> /var/log/dce-backup.log 2>&1
EOF
```

```bash
sudo chmod 0644 /etc/cron.d/dce-backup
```

Mount a separate volume at `/srv/dce/backups` if you have one (SDD 21.3). Rehearse a restore (section 15) on a copy before the demo. That is not part of go-live.

### G37. Run containment tests T01 to T12 on the VM

Follow `scripts/containment-checklist.md` in order. Run T02 to T04 and T09 (destructive) only outside demo hours. The manual `dce_run` helper needs root, because the admin user is not in the `docker` group:

```bash
sudo -i
```

After T02 to T04, record host availability (the evidence folder is in the admin home, not in `/srv/dce/backups`):

```bash
export BASE=https://commander.basyid.dev && mkdir -p ~/dce-evidence && for i in $(seq 1 20); do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' "$BASE/api/health"; sleep 1; done | tee ~/dce-evidence/health-after-hostile.log
```

Expect 20 lines starting with `200`, each under `1.000` seconds. Delete `/tmp/dce-analyst.cookies` after the session.

### G38. Set the spend alert

Vultr console, manual. Set a spend alert or limit (Appendix E).

---

## 1. Create the VM

In the Vultr console:

| Setting | Value |
| --- | --- |
| Type | Cloud Compute, regular performance |
| Size | 2 vCPU, 4 GB RAM, 80 GB SSD (SDD 5.5) |
| OS | Ubuntu LTS (current LTS release) |
| Region | Closest to the demo audience |
| SSH key | Add your public key. Do not use a password |
| Backups | Optional. The application backups in step 14 are the primary mechanism |

Note the public IPv4 address as `<VM_IPV4>`. Confirm the monthly price in the console, because the Appendix E figures are estimates.

## 2. DNS

Create an A record in the `basyid.dev` zone:

| Name | Type | Value | TTL |
| --- | --- | --- | --- |
| `commander` | A | `<VM_IPV4>` | 300 |

Verify from your laptop before continuing. Caddy cannot obtain a certificate until this resolves:

```bash
dig +short commander.basyid.dev
```

The output must be `<VM_IPV4>`.

## 3. First login and admin IP

From your laptop:

```bash
ssh root@<VM_IPV4>        # or the default Ubuntu user, then sudo
```

Create a non-root admin user if the provider image does not already have one, and add it to the `sudo` group. Log in as that user for the rest of the steps. Keep one terminal session open at all times while changing SSH settings.

## 4. Get the code

```bash
sudo mkdir -p /srv/dce
sudo git clone <REPO_URL> /srv/dce/app
```

The application path is `/srv/dce/app`. The frontend is deployed from it in step 9.

## 5. Run the VM bootstrap

`setup-vm.sh` is idempotent. Run it with the admin IP and the domain:

```bash
cd /srv/dce/app
sudo ADMIN_IP=<YOUR_ADMIN_IPV4> DOMAIN=commander.basyid.dev bash deployment/vultr/setup-vm.sh
```

The script installs Docker Engine and Caddy from their official apt repositories, creates the `dce` and `dce-sandbox` users, writes the UFW rules (SSH from the admin IP only, HTTP and HTTPS public), creates `/srv/dce` directories with the right owners, enables fail2ban and unattended upgrades, and prints the next steps.

Check the firewall before going on:

```bash
sudo ufw status verbose
```

Port 22 must be allowed only from `<YOUR_ADMIN_IPV4>`. Ports 80 and 443 must be allowed.

## 6. Harden SSH (key-only)

Confirm that key login works from a second terminal before changing anything. Then create a drop-in file:

```bash
sudo tee /etc/ssh/sshd_config.d/10-dce-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

Open a new session and confirm login still works. Keep the old session open until you do. If the test fails, remove the drop-in file and reload again.

## 7. Create the production `.env`

Start from the template. Keep the file in the repo root, where `docker-compose.yml` reads it:

```bash
cd /srv/dce/app
sudo install -m 0640 -o root -g dce .env.example .env
sudo nano .env        # or your editor. Do not paste secrets into shell commands.
```

Set these values (the rest keep their defaults from `.env.example`):

| Variable | Production value |
| --- | --- |
| `DCE_ENV` | `production` |
| `DCE_SERVE_FRONTEND` | `false` (Caddy serves the frontend) |
| `DCE_COOKIE_SECURE` | `true` |
| `DCE_INFERENCE_MODE` | `vultr` |
| `DCE_INFERENCE_MODEL` | the model ID from the Vultr list |
| `DCE_VULTR_INFERENCE_KEY` | your inference key |
| `DCE_SANDBOX_RUNNER` | `docker` |
| `DCE_SANDBOX_IMAGE` | set in step 11 |
| `DCE_SANDBOX_MAX_CONCURRENT` | `1` (2 vCPU VM) |
| `DCE_SEED_PASSWORD` | strong password, used only for step 12, then removed |

Confirm the file mode is `0640` and the group is `dce`:

```bash
ls -l /srv/dce/app/.env
```

`.env` must never be committed. It is listed in `.gitignore`.

## 8. Sandbox runtime

Choose one path (decision in the go-live checklist, G15):

1. **Rootless Docker (preferred by SDD 9.3a).** Follow `deployment/vultr/rootless-docker.md`, sections 1 to 3 and 5, and build the worker image through the rootless socket (step 11). The compose file does not connect the api container to the rootless daemon yet (`docs/security.md`, section 7, item 2). Until that is built, this path is not usable with `docker-compose.yml`.
2. **Socket proxy (what `docker-compose.yml` runs today).** The `docker-socket-proxy` service is already in the compose file. Check the proxy tag and pin it by digest first (see the comment in the compose file). Record the choice in `docs/security.md`.

Both paths need the seccomp profile on the host at `/srv/sandbox/seccomp/profile.json` (checklist G16).

## 9. Deploy the frontend

The frontend is static files. Copy them into the directory Caddy serves:

```bash
sudo rsync -a --delete /srv/dce/app/frontend/ /srv/dce/frontend/
sudo chmod -R a+rX /srv/dce/frontend
```

Repeat this command for every frontend release.

## 10. Caddy (automatic HTTPS)

Install the production configuration, validate it, then reload:

```bash
sudo install -m 0644 /srv/dce/app/deployment/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo journalctl -u caddy -n 50 --no-pager
```

Use `restart` the first time. Caddy is enabled but not running after `setup-vm.sh`, so `reload` would fail. Later changes can use `reload`.

Look for `certificate obtained successfully` in the log. Let's Encrypt needs ports 80 and 443 open and the DNS record from step 2.

The static site is up now. `/api/*` returns `502` until the backend starts in step 12.

## 11. Build and record the worker image

The worker image is built from `sandbox/`. Its digest is written by the script, never typed by hand:

```bash
cd /srv/dce/app
sudo docker login <registry-host>                # token is stored under /root (Docker credential store)
sudo env DCE_WORKER_REGISTRY=<registry-host>/<namespace> bash deployment/vultr/build-worker-image.sh
```

The Docker daemon is root-only, and the admin user is not in the `docker` group, so these run with `sudo`.

If you use rootless Docker, the image must land in the rootless daemon (`deployment/vultr/rootless-docker.md`, section 4). Build as `dce-sandbox`, which has no login shell and no sudo rights, so run it through `sudo -u`. Log in to the registry as that user first:

```bash
DS_UID=$(id -u dce-sandbox)
sudo -u dce-sandbox -H env XDG_RUNTIME_DIR=/run/user/$DS_UID DOCKER_HOST=unix:///run/user/$DS_UID/docker.sock docker login <registry-host>
sudo -u dce-sandbox -H env XDG_RUNTIME_DIR=/run/user/$DS_UID DOCKER_HOST=unix:///run/user/$DS_UID/docker.sock DCE_WORKER_REGISTRY=<registry-host>/<namespace> bash /srv/dce/app/deployment/vultr/build-worker-image.sh
```

The script prints a line like `<registry-host>/<namespace>/dce-worker@sha256:...` and writes it to `deployment/vultr/worker-image.digest`. Copy that value into `DCE_SANDBOX_IMAGE` in `.env` (step 7). Keep the digest file out of editing by hand.

## 12. Start the backend and seed accounts

Build and start the API. The API listens on `127.0.0.1:8000` on the host, and Caddy proxies `/api/*` to it:

```bash
cd /srv/dce/app
sudo docker compose -f deployment/docker-compose.yml --env-file .env up -d --build
sudo docker compose -f deployment/docker-compose.yml --env-file .env ps
```

Create the seed accounts (admin, analyst, reviewer, approver). Read the password from the terminal, so it is not stored in shell history or in `.env`. `--preserve-env` passes it through `sudo`:

```bash
read -rs DCE_SEED_PASSWORD && export DCE_SEED_PASSWORD
cd /srv/dce/app && sudo --preserve-env=DCE_SEED_PASSWORD docker compose -f deployment/docker-compose.yml --env-file .env run --rm -e DCE_SEED_PASSWORD api python -m app.seed
unset DCE_SEED_PASSWORD
```

Then remove `DCE_SEED_PASSWORD` from `.env` and recreate the API, so the running container no longer holds it (the checklist, G34, has the same steps):

```bash
sudo sed -i '/^DCE_SEED_PASSWORD=/d' /srv/dce/app/.env
cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env up -d api
```

Check liveness through the public URL:

```bash
curl -s https://commander.basyid.dev/api/health    # expect {"status":"ok"}
```

## 13. Smoke test

Run the smoke test from your admin laptop, against the public URL. Use Python 3 from the repo and the seed password from your shell (not stored in a file):

```bash
read -rs DCE_SEED_PASSWORD && export DCE_SEED_PASSWORD
python scripts/smoke.py --base-url https://commander.basyid.dev
unset DCE_SEED_PASSWORD
```

Every row must show `PASS`. Keep the table as evidence for the demo. Then run the containment checklist (`scripts/containment-checklist.md`), in particular T12, because it checks that the host stays responsive.

## 14. Backups (SDD 21.3)

`scripts/backup.sh` takes a consistent SQLite snapshot with `sqlite3 .backup`, checks it, writes a SHA-256 sidecar, and keeps the newest seven copies.

Test it once by hand, as the `dce` user:

```bash
sudo -u dce env DCE_DATABASE_PATH=/srv/dce/data/dce.sqlite3 DCE_BACKUP_DIR=/srv/dce/backups \
  /bin/bash /srv/dce/app/scripts/backup.sh
sudo ls -l /srv/dce/backups
```

Schedule it nightly at 02:17 UTC with a cron file. `/bin/bash` is explicit, so the script does not need the executable bit on the checkout. `setup-vm.sh` creates `/var/log/dce-backup.log` owned by `dce`, because cron opens that file as `dce`:

```bash
sudo tee /etc/cron.d/dce-backup >/dev/null <<'EOF'
SHELL=/bin/bash
17 2 * * * dce DCE_DATABASE_PATH=/srv/dce/data/dce.sqlite3 DCE_BACKUP_DIR=/srv/dce/backups /bin/bash /srv/dce/app/scripts/backup.sh >> /var/log/dce-backup.log 2>&1
EOF
sudo chmod 0644 /etc/cron.d/dce-backup
```

The backup directory should be on a separate volume when possible (SDD 21.3). Mount it at `/srv/dce/backups` before enabling the cron job. Keep the script's seven-copy retention.

## 15. Restore (tested before the demo)

Restore is a manual procedure. `scripts/restore.sh` automates the file swap, and it refuses to run while the API is up.

1. Pick the snapshot: `sudo ls -lt /srv/dce/backups/dce-*.sqlite3`.
2. Stop the API: `cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env stop api`.
3. Restore: `sudo bash /srv/dce/app/scripts/restore.sh /srv/dce/backups/dce-<stamp>.sqlite3`. The current database is kept as `dce.sqlite3.replaced-<stamp>`.
4. Start the API: `cd /srv/dce/app && sudo docker compose -f deployment/docker-compose.yml --env-file .env up -d api`.
5. Check health: `curl -s https://commander.basyid.dev/api/health`.
6. Check the audit chain as Admin: `POST /api/audit/verify`. A failure means the snapshot is not usable. Try an older one.
7. Orphaned tasks: the application marks interrupted tasks `ORPHANED` on startup (SDD 21.3). They are never resumed automatically.

Rehearse this once on a copy of the VM or a local machine before the demo, and record the date in the operator log.

## 16. Post-deploy checklist

- [ ] `https://commander.basyid.dev` loads with a valid certificate.
- [ ] `/api/health` returns `{"status":"ok"}`.
- [ ] `DCE_SEED_PASSWORD` is not in `.env`, and no secret is in the repo (`git status` clean).
- [ ] `ufw status` shows SSH limited to the admin IP.
- [ ] Smoke test passes.
- [ ] Containment checklist T01 to T12 has evidence.
- [ ] Backup cron ran once, and one restore rehearsal passed.
- [ ] Vultr spend alert or limit is set in the console (Appendix E).

## Cost summary (SDD Appendix E)

Prices were checked on November 5, 2026 and must be re-verified in the Vultr console before deployment.

| Item | Per month (USD) | Basis |
| --- | --- | --- |
| VM 2 vCPU / 4 GB, 80 GB SSD | about 24 | Third-party listings range from $20 to $24 |
| Serverless Inference | about 10 | $0.55 per M input and $2.75 per M output tokens (March 2026). About $0.008 per agent task |
| Frontend hosting | 0 | Served from the same VM (v1.6). Appendix E still says existing hosting; that line is outdated |
| Domain | about 15 per year | Only if you do not already own one |
| Contingency (about 20%) | about 7 | Buffer |
| **Total, 2 vCPU VM** | **about 40 to 45** | |
| **Total, 4 vCPU / 8 GB VM** | about 60 to 70 | Not verified. Needed only for concurrency 2 |

Each participant receives $200 in Vultr credits through the lablab.ai page. With the 2 vCPU VM, the credits cover several months. Extra IPv4 addresses and block storage are billed separately. The inference quota (SDD 20.6) is the main budget control.

## Desktop build (Windows)

The desktop app is a Tauri 2 shell (`src-tauri/`) that opens `https://commander.basyid.dev` in a native window. It is the same origin as the API, so the session cookie works. It is not a separate build of the frontend.

- Prerequisites on the build machine: Node.js, Rust (MSVC toolchain), Visual Studio Build Tools with the C++ workload, and WebView2 on the target machine.
- Build (from the repo root, PowerShell): `powershell -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1`. The script loads `vcvars64.bat` from the installed Visual Studio (found with `vswhere`) and then runs `npm run build:desktop`.
- Output: `src-tauri\target\release\bundle\nsis\` (NSIS `.exe`) and `src-tauri\target\release\bundle\msi\` (`.msi`).
- If the build fails with `Access denied` on `src-tauri\target` (the repo sits in OneDrive), set `CARGO_TARGET_DIR` to a folder outside OneDrive before running the script. The bundles then appear under `<CARGO_TARGET_DIR>\release\bundle\`.
- The MSI bundler downloads the WiX 3.14 toolset from GitHub on first use. A GitHub outage (HTTP 504) fails the MSI step. Retry later.
- Not included: code signing. Windows shows an unknown-publisher warning. The first launch needs network access.
