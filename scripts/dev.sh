#!/usr/bin/env bash
# Disaster Commander Edge - local development launcher for macOS and Linux.
#
# Usage (from the repo root):
#   ./scripts/dev.sh                 # create .venv if needed, install deps, start the server
#   ./scripts/dev.sh --skip-install  # skip pip install
#
# Seeding: export DCE_SEED_PASSWORD for this shell only, then run the script.
#   read -rs DCE_SEED_PASSWORD && export DCE_SEED_PASSWORD
# The password is never written to disk.
#
# Sandbox: if Docker is reachable, DCE_SANDBOX_RUNNER defaults to docker. Otherwise it defaults to
# local, which is NOT isolated. Local mode is for development with trusted inputs only.

set -euo pipefail

SKIP_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help)
      sed -n '2,11p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
REQUIREMENTS="$BACKEND_DIR/requirements.txt"
URL="http://127.0.0.1:8000"

step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

# --- 1. Python and virtual environment -------------------------------------
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  step "Creating backend/.venv"
  PY="$(command -v python3.12 || command -v python3 || true)"
  [[ -n "$PY" ]] || { echo "python3 (3.12+) not found on PATH." >&2; exit 1; }
  "$PY" -m venv "$VENV_DIR"
else
  step "Using existing backend/.venv"
fi
VENV_PY="$VENV_DIR/bin/python"

# --- 2. Dependencies ------------------------------------------------------
if [[ "$SKIP_INSTALL" -eq 1 ]]; then
  step "Skipping dependency install (--skip-install)"
else
  step "Installing backend requirements"
  [[ -f "$REQUIREMENTS" ]] || { echo "Missing $REQUIREMENTS." >&2; exit 1; }
  "$VENV_PY" -m pip install --upgrade pip --quiet
  "$VENV_PY" -m pip install -r "$REQUIREMENTS"
fi

# --- 3. Sandbox runner selection ------------------------------------------
DOCKER_OK=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  DOCKER_OK=1
fi

if [[ -z "${DCE_SANDBOX_RUNNER:-}" ]]; then
  if [[ "$DOCKER_OK" -eq 1 ]]; then
    export DCE_SANDBOX_RUNNER=docker
  else
    export DCE_SANDBOX_RUNNER=local
  fi
fi

step "Sandbox runner: $DCE_SANDBOX_RUNNER"
if [[ "$DCE_SANDBOX_RUNNER" == "local" ]]; then
  warn "LOCAL sandbox mode is NOT isolated. Generated code runs as your user. Production must use docker."
fi
if [[ "$DCE_SANDBOX_RUNNER" == "docker" && "$DOCKER_OK" -eq 0 ]]; then
  warn "DCE_SANDBOX_RUNNER=docker but 'docker info' failed. Agent tasks will fail until Docker is running."
fi
export DCE_ENV="${DCE_ENV:-development}"

# --- 4. Seed (only when the password is in the environment) ----------------
cd "$BACKEND_DIR"
if [[ -n "${DCE_SEED_PASSWORD:-}" ]]; then
  step "Seeding development accounts (DCE_SEED_PASSWORD is set)"
  "$VENV_PY" -m app.seed
else
  step "Skipping seed (export DCE_SEED_PASSWORD in this shell to seed the demo accounts)"
fi

# --- 5. Start the server --------------------------------------------------
step "Starting uvicorn on $URL (Ctrl+C to stop)"
echo "Open: $URL"
exec "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
