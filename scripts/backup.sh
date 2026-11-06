#!/usr/bin/env bash
# Nightly SQLite backup for Disaster Commander Edge (SDD 21.3).
#
# Uses sqlite3 ".backup", which takes a consistent snapshot while the API keeps running
# (WAL mode). Plain file copies can miss -wal content, so do not use cp for backups.
#
# Each run:
#   1. Writes a snapshot to DCE_BACKUP_DIR with a UTC timestamp.
#   2. Checks it with PRAGMA integrity_check (must print "ok").
#   3. Writes a SHA-256 sidecar file.
#   4. Keeps the newest DCE_BACKUP_KEEP snapshots (default 7) and removes older ones.
#
# Schedule nightly as the dce user with /etc/cron.d/dce-backup (see docs/deployment.md):
#   17 2 * * * dce DCE_DATABASE_PATH=/srv/dce/data/dce.sqlite3 DCE_BACKUP_DIR=/srv/dce/backups /bin/bash /srv/dce/app/scripts/backup.sh >> /var/log/dce-backup.log 2>&1
# (/bin/bash is explicit so the script does not need the executable bit on the checkout.)
#
# Environment:
#   DCE_DATABASE_PATH   default /srv/dce/data/dce.sqlite3
#   DCE_BACKUP_DIR      default /srv/dce/backups (mount a separate volume here when possible)
#   DCE_BACKUP_KEEP     default 7

set -euo pipefail

DB="${DCE_DATABASE_PATH:-/srv/dce/data/dce.sqlite3}"
BACKUP_DIR="${DCE_BACKUP_DIR:-/srv/dce/backups}"
KEEP="${DCE_BACKUP_KEEP:-7}"

die() { printf '%s ERROR: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; exit 1; }

command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is not installed (apt-get install sqlite3)."
[[ -f "$DB" ]] || die "database not found: $DB"
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 1 ]] || die "DCE_BACKUP_KEEP must be a positive integer."

install -d -m 0750 "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/dce-$STAMP.sqlite3"
TMP="$DEST.partial"

# Snapshot into a temporary name, then rename, so a half-written file never looks like a backup.
trap 'rm -f "$TMP"' EXIT
sqlite3 "$DB" ".timeout 5000" ".backup '$TMP'"

CHECK="$(sqlite3 "$TMP" 'PRAGMA integrity_check;')"
if [[ "$CHECK" != "ok" ]]; then
  die "integrity_check failed for snapshot: $CHECK"
fi

mv "$TMP" "$DEST"
chmod 0600 "$DEST"
( cd "$BACKUP_DIR" && sha256sum "$(basename "$DEST")" > "$(basename "$DEST").sha256" )
trap - EXIT

echo "$(date -u +%FT%TZ) OK backup=$DEST"

# Retention: keep the newest $KEEP snapshots and their checksum files.
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/dce-*.sqlite3 2>/dev/null | tail -n +"$((KEEP + 1))")
for f in "${OLD[@]}"; do
  rm -f -- "$f" "$f.sha256"
  echo "$(date -u +%FT%TZ) pruned=$f"
done
