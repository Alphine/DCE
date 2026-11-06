#!/usr/bin/env bash
# Build the sandbox worker image from sandbox/, push it, and record its digest (SDD 9.3, 9.8).
#
# The digest is written by this script, never typed by hand. A tag alone is not enough
# because SDD 9.3 requires the worker image to be pinned by digest.
#
# Usage (from the repo root):
#   DCE_WORKER_REGISTRY=registry.example.com/dce ./deployment/vultr/build-worker-image.sh
#
# Environment:
#   DCE_WORKER_REGISTRY   required to record a digest. Registry and namespace to push to.
#   DCE_WORKER_TAG        optional. Default: short git SHA, or a UTC timestamp.
#   DOCKER_HOST           optional. Set it to the rootless daemon socket when building for
#                         rootless Docker, because images are stored per daemon, for example:
#                         DOCKER_HOST=unix:///run/user/<uid-of-dce-sandbox>/docker.sock
#   DCE_WORKER_ALLOW_LOCAL=1  build locally without pushing. No digest is recorded, so the
#                         result is for development only and cannot be used in production.
#
# Output: deployment/vultr/worker-image.digest (one line, e.g. registry/dce-worker@sha256:...).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SANDBOX_DIR="$REPO_ROOT/sandbox"
DIGEST_FILE="$SCRIPT_DIR/worker-image.digest"

IMAGE_NAME="dce-worker"
REGISTRY="${DCE_WORKER_REGISTRY:-}"
ALLOW_LOCAL="${DCE_WORKER_ALLOW_LOCAL:-0}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."
docker info >/dev/null 2>&1 || die "cannot reach the Docker daemon (check DOCKER_HOST and permissions)."
[[ -f "$SANDBOX_DIR/Dockerfile" ]] || die "missing $SANDBOX_DIR/Dockerfile."

TAG="${DCE_WORKER_TAG:-}"
if [[ -z "$TAG" ]]; then
  TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ -z "$REGISTRY" && "$ALLOW_LOCAL" != "1" ]]; then
  die "set DCE_WORKER_REGISTRY to record a digest, or DCE_WORKER_ALLOW_LOCAL=1 for a development-only local build."
fi

LOCAL_REF="$IMAGE_NAME:$TAG"
echo "==> Building $LOCAL_REF from $SANDBOX_DIR"
docker build --pull -t "$LOCAL_REF" -f "$SANDBOX_DIR/Dockerfile" "$SANDBOX_DIR"

if [[ -z "$REGISTRY" ]]; then
  echo "==> Local build only (DCE_WORKER_ALLOW_LOCAL=1). No digest recorded."
  echo "    Image ID: $(docker inspect --format '{{.Id}}' "$LOCAL_REF")"
  echo "    Use DCE_SANDBOX_IMAGE=$LOCAL_REF for development only."
  exit 0
fi

REMOTE_REF="$REGISTRY/$IMAGE_NAME:$TAG"
echo "==> Pushing $REMOTE_REF"
docker tag "$LOCAL_REF" "$REMOTE_REF"
docker push "$REMOTE_REF"

# RepoDigests is populated only after a push or pull. Index 0 is "<repo>@sha256:<digest>".
REPO_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "$REMOTE_REF" 2>/dev/null || true)"
[[ -n "$REPO_DIGEST" && "$REPO_DIGEST" == *"@sha256:"* ]] || die "could not read the repo digest after push."

printf '%s\n' "$REPO_DIGEST" > "$DIGEST_FILE"
chmod 0644 "$DIGEST_FILE"

echo "==> Digest recorded in $DIGEST_FILE"
echo "$REPO_DIGEST"
echo
echo "Set this in the VM .env (never in the repo):"
echo "  DCE_SANDBOX_IMAGE=$REPO_DIGEST"
