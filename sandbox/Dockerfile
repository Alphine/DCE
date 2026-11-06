# DCE sandbox worker image (SDD 9.3). The image runs generated Python with no network and no secrets.
#
# PRODUCTION: pin the base image by digest, not by tag, for example
#   FROM python:3.12-slim@sha256:<digest>
# Record the digest of the built worker image (dce-worker@sha256:...) in the deployment docs, and set
# DCE_SANDBOX_IMAGE to that digest. The tag below is for local development only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Worker code is root-owned and read-only for the run user (65534).
COPY worker.py /sandbox/worker.py
RUN chmod 0444 /sandbox/worker.py \
    && mkdir -p /workspace \
    && chmod 0755 /workspace

# Runtime /workspace is a tmpfs mounted by `docker create` (noexec,nosuid, 100 MB). See SDD 9.3.
WORKDIR /workspace

# Run as the unprivileged uid/gid 65534 (nobody). The container is also started with --user 65534:65534.
USER 65534:65534

ENTRYPOINT ["python", "/sandbox/worker.py"]
