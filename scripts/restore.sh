#!/usr/bin/env bash
# Restore the SQLite database from a backup made by scripts/backup.sh (SDD 21.3).
#
# Run on the VM as root, with the API stopped. The script refuses to run while the API is up.
#
#   sudo ./scripts/restore.sh /srv/dce/backups/dce-20261105T021700Z.sqlite3
#
# Steps:
#   1. Verify the .sha256 sidecar and PRAGMA integrity_check of the backup.
#   2. Move the current database aside (kept, never deleted) with its WAL and SHM files.
#   3. Copy the backup into place with the owner the container expects (uid 10001).
#   4. Start the API again. Check health and the audit chain by hand (docs/deployment.md).

set -euo pipefail

DB="${DCE_DATABASE_PATH:-/srv/dce/data/dce.sqlite3}"
COMPOSE_FILE="${DCE_COMPOSE_FILE:-/srv/dce/app/deployment/docker-compose.yml}"
ENV_FILE="${DCE_ENV_FILE:-/srv/dce/app/.env}"
BACKUP="${1:-}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root."
[[ -n "$BACKUP" && -f "$BACKUP" ]] || die "usage: $0 <backup-file.sqlite3>"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is not installed."

if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps --status running --services 2>/dev/null | grep -qx api; then
  die "the api service is running. Stop it first: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE stop api"
fi

echo "==> Verifying checksum"
if [[ -f "$BACKUP.sha256" ]]; then
  ( cd "$(dirname "$BACKUP")" && sha256sum -c "$(basename "$BACKUP").sha256" )
else
  die "missing $BACKUP.sha256. Refusing to restore an unverified backup."
fi

echo "==> Verifying integrity"
CHECK="$(sqlite3 "$BACKUP" 'PRAGMA integrity_check;')"
[[ "$CHECK" == "ok" ]] || die "integrity_check failed: $CHECK"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
echo "==> Moving the current database aside (kept for forensics)"
if [[ -f "$DB" ]]; then
  mv "$DB" "$DB.replaced-$STAMP"
  for side in "$DB-wal" "$DB-shm"; do
    [[ -f "$side" ]] && mv "$side" "$side.replaced-$STAMP"
  done
fi

echo "==> Restoring"
install -m 0600 -o 10001 -g 10001 "$BACKUP" "$DB"

echo "==> Restored. Start the API and verify:"
echo "    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d api"
echo "    curl -s http://127.0.0.1:8000/api/health"
echo "    Then POST /api/audit/verify as Admin."
