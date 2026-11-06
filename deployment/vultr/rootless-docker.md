# Rootless Docker for the sandbox (SDD 9.3a)

This is the preferred way for the Sandbox Dispatcher to create worker containers. The Docker daemon runs under the unprivileged `dce-sandbox` user. A compromised dispatcher then controls only that user's daemon, not the host root.

Use the socket proxy path (end of this file) only if rootless Docker cannot run on the VM.

## 1. Prerequisites

`setup-vm.sh` creates `dce-sandbox` (no sudo, no login shell). Install the rootless helpers as root:

```bash
sudo apt-get install -y uidmap dbus-user-session slirp4netns fuse-overlayfs
```

Confirm subordinate ID ranges exist for `dce-sandbox`:

```bash
grep dce-sandbox /etc/subuid /etc/subgid
```

If they are missing, add them (`sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 dce-sandbox`).

## 2. Stop the rootful daemon for this host (recommended)

If the VM runs only the rootless daemon for worker containers, disable the rootful one so the two do not compete:

```bash
sudo systemctl disable --now docker.service docker.socket
```

The rootful daemon is still needed to build the backend image on the admin side. If you keep it, do not add any app user to the `docker` group.

## 3. Install rootless Docker as dce-sandbox

Enable lingering so the user's systemd session survives without a login:

```bash
sudo loginctl enable-linger dce-sandbox
DS_UID=$(id -u dce-sandbox)
sudo -u dce-sandbox -H env XDG_RUNTIME_DIR=/run/user/$DS_UID bash -c \
  'dockerd-rootless-setuptool.sh install'
```

If the `dockerd-rootless-setuptool.sh` command is missing, install the Docker rootless extras package (`docker-ce-rootless-extras`) from the Docker apt repository set up by `setup-vm.sh`.

Check the rootless daemon:

```bash
sudo -u dce-sandbox -H env XDG_RUNTIME_DIR=/run/user/$DS_UID \
  DOCKER_HOST=unix:///run/user/$DS_UID/docker.sock docker info | grep -i rootless
```

Expect `rootless` in the security options.

## 4. Use the rootless socket

The rootless socket is `unix:///run/user/<uid-of-dce-sandbox>/docker.sock`. Only `dce-sandbox` can open it. The backend (`dce`) must not read it directly. The dispatcher runs as `dce-sandbox` and exposes only the operations in SDD 9.3a. The exact dispatcher-to-backend IPC is not specified yet. This is an open item in `docs/security.md`.

Build and load the worker image into the rootless daemon. Images are per daemon:

```bash
DOCKER_HOST=unix:///run/user/$DS_UID/docker.sock \
DCE_WORKER_REGISTRY=registry.example.com/dce \
  ./deployment/vultr/build-worker-image.sh
```

Pulling by digest from the registry is the normal production path. `docker save | docker load` also works, but then the digest comes from the local image and must be checked against the value in `deployment/vultr/worker-image.digest`.

Set in the VM `.env` (not in the repo):

```
DCE_SANDBOX_RUNNER=docker
DCE_SANDBOX_IMAGE=<registry>/dce-worker@sha256:<digest>
```

## 5. Verify rootless containment

```bash
sudo -u dce-sandbox -H env DOCKER_HOST=unix:///run/user/$DS_UID/docker.sock \
  docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user 65534:65534 \
  --memory 512m --memory-swap 512m --pids-limit 64 \
  <digest> id
```

Expect the output `uid=65534`. Confirm `docker info` shows `rootless`. The host `/` is not reachable from the container because nothing is bind-mounted.

## 6. Fallback: Docker socket proxy (rootful daemon)

Use this only if rootless Docker cannot run. The compose file in `deployment/docker-compose.yml` already defines this path:

- Only `docker-socket-proxy` mounts `/var/run/docker.sock`, read-only.
- The proxy sits on an internal network with no egress.
- `CONTAINERS=1`, `IMAGES=1`, and `POST=1` are the only sections enabled. `ALLOW_RESTARTS`, privileged options, and similar options stay disabled.
- The backend reaches the proxy as `DOCKER_HOST=tcp://docker-socket-proxy:2375`.

Known limit: the proxy filters by API section, not by path or request body. `CONTAINERS=1` allows every container endpoint. SDD 9.3a requires finer rules: a path allowlist, and rejection of `Privileged`, `Binds`, `CapAdd`, a non-`none` `NetworkMode`, and non-default `PidMode` or `IpcMode`. Those checks must be enforced in the dispatcher before a create request is sent. The proxy alone does not provide them. Treat the proxy path as weaker than rootless and record it as a residual risk in `docs/security.md`.

The worker container must never receive the Docker socket or the proxy address (SDD 9.3a, last bullet).
