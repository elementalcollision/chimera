# Chimera runtime container — v4.45.
#
# Multi-stage build with uv. Stage 1 installs deps + chimera into
# /opt/venv. Stage 2 is a slim runtime with the venv + tool-ring shells.
#
# Build:  docker compose build chimera
# Run:    docker compose run --rm chimera ping --provider both
# Cycle:  docker compose run --rm chimera run "task text here"

ARG PYTHON_VERSION=3.12

# ─────────────────────────── build ───────────────────────────
FROM python:${PYTHON_VERSION}-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin uv.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Copy lock + manifest first for layer caching.
COPY pyproject.toml uv.lock* README.md ./
COPY chimera ./chimera

# Build into /opt/venv. ``uv pip install`` honours --python; ``uv sync``
# silently writes to ``.venv`` regardless, so we use the former.
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python -e .

# ───────────────────────── runtime ───────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    CHIMERA_STATE_DIR=/state \
    CHIMERA_MIND_DIR=/mind \
    CHIMERA_PEER_REGISTRY_DIR=/peers

# Tool-ring binaries: shell, git for skill assembly, curl/jq for
# diagnostics, ripgrep for AST scans. Tight list — expansion is gated
# by the dispatch policy, not the image (ADR 0001 §sandbox).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        curl \
        jq \
        ripgrep \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID/GID 1000 to match the typical host user so volume
# mounts work without permission gymnastics.
RUN groupadd --gid 1000 chimera && \
    useradd  --uid 1000 --gid 1000 --shell /bin/bash --create-home chimera

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/chimera /app/chimera
COPY pyproject.toml README.md /app/
WORKDIR /app

# Pre-create persistent dirs so first-cycle bootstrap doesn't trip on
# perms.
RUN mkdir -p /state /mind /peers && \
    chown -R chimera:chimera /state /mind /peers /app

USER chimera

# HEALTHCHECK: the doctor verb imports + validates env on every call.
# 30s start window covers first-load import cost of kuzu + sqlite3.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD chimera doctor 2>&1 | grep -qE "(ok|✓)" || exit 1

# tini reaps zombies from sub-agent subprocesses cleanly.
ENTRYPOINT ["/usr/bin/tini", "--", "chimera"]
CMD ["--help"]
