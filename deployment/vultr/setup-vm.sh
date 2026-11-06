#!/usr/bin/env bash
# Disaster Commander Edge - idempotent bootstrap for an Ubuntu LTS Vultr VM (SDD sections 5.5, 9.3a, 21.3).
#
# Run as root (or via sudo) on a fresh Ubuntu LTS VM:
#   sudo ADMIN_IP=203.0.113.10 DOMAIN=commander.basyid.dev bash deployment/vultr/setup-vm.sh
#
# Environment variables (no secrets are read or written by this script):
#   ADMIN_IP   required. Public IPv4 allowed to reach SSH (port 22). Use a /32 address.
#   DOMAIN     optional. Informational; printed at the end. Default commander.basyid.dev.
#   WITH_FAIL2BAN   optional. 1 (default) installs fail2ban. 0 skips it.
#
# Re-running is safe: every step checks the current state before changing it.

set -euo pipefail

log()  { printf '\n==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root (sudo)."
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "this script targets Ubuntu LTS (found: ${ID:-unknown})."

ADMIN_IP="${ADMIN_IP:-}"
DOMAIN="${DOMAIN:-commander.basyid.dev}"
WITH_FAIL2BAN="${WITH_FAIL2BAN:-1}"
[[ -n "$ADMIN_IP" ]] || die "ADMIN_IP is required (the public IPv4 allowed to SSH)."
if ! [[ "$ADMIN_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  die "ADMIN_IP must be a plain IPv4 address, for example 203.0.113.10."
fi

export DEBIAN_FRONTEND=noninteractive
ARCH="$(dpkg --print-architecture)"
CODENAME="${UBUNTU_CODENAME:-$VERSION_CODENAME}"

# ---------------------------------------------------------------------------
log "Base packages and apt update"
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg ufw sqlite3 unattended-upgrades apt-transport-https git rsync

# ---------------------------------------------------------------------------
log "Docker Engine from the official apt repository"
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
DOCKER_LIST=/etc/apt/sources.list.d/docker.list
DOCKER_LINE="deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable"
if [[ ! -f "$DOCKER_LIST" ]] || ! grep -qxF "$DOCKER_LINE" "$DOCKER_LIST"; then
  printf '%s\n' "$DOCKER_LINE" > "$DOCKER_LIST"
fi
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# ---------------------------------------------------------------------------
log "Unprivileged users"
# dce: runs the backend, owns /srv/dce/data. uid/gid 10001 matches the container user (deployment/Dockerfile.backend).
if ! getent group dce >/dev/null; then groupadd --system --gid 10001 dce; fi
if ! id -u dce >/dev/null 2>&1; then
  useradd --system --uid 10001 --gid dce --home-dir /srv/dce --shell /usr/sbin/nologin dce
fi
# dce-sandbox: owns the rootless Docker daemon (SDD 9.3a, preferred). No sudo, no login shell.
if ! id -u dce-sandbox >/dev/null 2>&1; then
  useradd --create-home --shell /usr/sbin/nologin dce-sandbox
fi
# Neither user joins the docker group. The docker group is root-equivalent.
for u in dce dce-sandbox; do
  if id -nG "$u" | tr ' ' '\n' | grep -qx docker; then
    gpasswd -d "$u" docker >/dev/null
  fi
done
# Explicitly ensure no sudo rights for either user.
rm -f /etc/sudoers.d/dce /etc/sudoers.d/dce-sandbox

# ---------------------------------------------------------------------------
log "Directories and permissions"
install -d -m 0755 -o root -g root /srv/dce
install -d -m 0755 -o root -g root /srv/dce/frontend        # static files, rsynced by deploy; world-readable for Caddy
install -d -m 0750 -o dce -g dce /srv/dce/data              # SQLite + artifacts (container uid 10001)
install -d -m 0750 -o dce -g dce /srv/dce/data/artifacts
install -d -m 0750 -o dce -g dce /srv/dce/backups           # nightly sqlite .backup target, written by the dce cron job (separate volume recommended)
install -d -m 0755 -o root -g root /srv/dce/app             # git checkout of this repo
install -d -m 0755 -o root -g root /var/log/caddy
chown caddy:caddy /var/log/caddy 2>/dev/null || true
# Secrets file is created by the operator, never by this script. Enforce its mode if it exists.
if [[ -f /srv/dce/app/.env ]]; then
  chown root:dce /srv/dce/app/.env
  chmod 0640 /srv/dce/app/.env
fi
# Seccomp profile for worker containers. The dispatcher passes this absolute path to the Docker
# daemon, so it must exist on the host at the same path that docker-compose.yml mounts.
if [[ -f /srv/dce/app/sandbox/seccomp/profile.json ]]; then
  install -D -m 0644 -o root -g root /srv/dce/app/sandbox/seccomp/profile.json /srv/sandbox/seccomp/profile.json
fi
# Backup cron log: the cron job (user dce) writes it with ">>", so dce must own it.
if [[ ! -f /var/log/dce-backup.log ]]; then
  install -m 0640 -o dce -g dce /dev/null /var/log/dce-backup.log
fi

# ---------------------------------------------------------------------------
log "Caddy from the official apt repository"
if [[ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]]; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
fi
if [[ ! -f /etc/apt/sources.list.d/caddy-stable.list ]]; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    -o /etc/apt/sources.list.d/caddy-stable.list
fi
apt-get update -y
apt-get install -y caddy
systemctl enable caddy

# ---------------------------------------------------------------------------
log "Firewall (UFW): SSH from admin IP only, HTTP and HTTPS public"
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$ADMIN_IP" to any port 22 proto tcp comment 'SSH admin only'
ufw allow 80/tcp comment 'HTTP (ACME, redirect)'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable
ufw status verbose

# ---------------------------------------------------------------------------
if [[ "$WITH_FAIL2BAN" == "1" ]]; then
  log "fail2ban (sshd jail)"
  apt-get install -y fail2ban
  cat > /etc/fail2ban/jail.d/dce-sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOF
  systemctl enable --now fail2ban
  systemctl restart fail2ban
fi

# ---------------------------------------------------------------------------
log "Unattended security upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades

# ---------------------------------------------------------------------------
log "Done"
cat <<EOF
Next steps (see docs/deployment.md):
  1. Confirm DNS: A record for ${DOMAIN} points at this VM public IPv4.
  2. Install the Caddyfile:  install -m 0644 deployment/Caddyfile /etc/caddy/Caddyfile && caddy validate --config /etc/caddy/Caddyfile
  3. Set up sandbox runtime: deployment/vultr/rootless-docker.md (preferred) or the socket proxy path.
  4. Clone the repo to /srv/dce/app and create /srv/dce/app/.env (mode 0640, group dce). Never commit it.
  5. Build the worker image: deployment/vultr/build-worker-image.sh
EOF
