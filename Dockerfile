# Chimera runtime container.
#
# Mirrors leonardo-daemon's python:3.12-slim choice (ADR 0001).
# Multi-stage build: deps install in `build`, runtime is slim.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY chimera ./chimera

RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels .

# ---- runtime ----
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHIMERA_STATE_DIR=/state \
    CHIMERA_MIND_DIR=/mind

# Shell utilities for MVP tool ring + diagnostics.
# Keep this list tight; expansion happens at later tool rings (ADR 0001 §sandbox).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        curl \
        jq \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels chimera \
    && rm -rf /wheels

# State and mind directories are docker volumes; create as fallback.
RUN mkdir -p /state/drift /mind/wiki

ENTRYPOINT ["chimera"]
CMD ["--help"]
