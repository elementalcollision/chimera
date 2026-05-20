# ADR 0064 — Container bootstrap (v4.45)

**Status:** Accepted (2026-05-19)

## Context

Chimera was running locally under `uv run` from the repo. That works
for development but ships zero of: process supervision, non-root
isolation, healthcheck-based restart, dashboard co-location, peer
HTTP exposure. [ADR 0001](./0001-sdk-chimera-boundaries.md) always intended Docker as the deployment
shape; v4.0 shipped a minimal Dockerfile (pip-wheel + slim runtime)
that's been bit-rotting since the dependency surface grew (kuzu,
better-sqlite3, ripgrep, jq, tini, Next.js dashboard).

## Decision

A two-image production-shape compose:

- **chimera** — long-running MCP HTTP server. Multi-stage Dockerfile
  using `uv` (10× faster than `pip wheel`), non-root user (UID/GID
  1000 for clean host-volume permissions), `tini` PID 1 to reap
  sub-agent zombies, healthcheck against `chimera doctor`.
- **dashboard** — Next.js 15 / Turbopack control plane. Three-stage
  build (deps → builder → runner) with the runtime ditching
  `build-essential`. Read-only volume mounts on `mind/` and `state/`
  — the dashboard never writes.

### Service shape

```
docker compose up -d
  ├─ chimera          0.0.0.0:8765 (MCP HTTP, bearer auth via CHIMERA_PEER_TOKEN)
  │   command: chimera serve --http --host 0.0.0.0 --port 8765
  │   healthcheck: curl /healthz
  │   volumes: ./mind ./state ./peers  (rw)
  └─ dashboard        0.0.0.0:3000 (Next.js)
      command: npm run start
      healthcheck: fetch :3000/
      volumes: ./mind ./state           (ro)
```

The compose binds both services to `127.0.0.1` by default — no
public exposure without explicit port re-mapping.

### One-shot mode

```
docker compose run --rm chimera run "task text"      # one cycle
docker compose run --rm chimera ping --provider both # smoke test
docker compose run --rm chimera doctor               # healthcheck dry-run
```

`run --rm` doesn't go through the long-running `serve` command; it
overrides CMD and exits when the cycle is done.

### Makefile verbs

| Target | Purpose |
|---|---|
| `make build` | both images |
| `make up` / `make down` | start/stop the long-running pair |
| `make logs` | tail both services |
| `make run ARGS="…"` | one-shot ad-hoc chimera invocation |
| `make cycle TASK="…"` | one-shot cycle on the given task |
| `make ping` | verify both providers inside the container |
| `make dashboard` | open http://127.0.0.1:3000 |
| `make test` / `make test-slow` | local pytest |

## Why uv inside the image

`pip wheel + pip install --no-index` was working but slow (~90s
build time for a clean image). `uv sync` is ~10s. The lockfile
(`uv.lock`) gives reproducible installs across builds; falls back to
`uv pip install -e .` when the lockfile is absent for headless CI.

## Why non-root + UID 1000

Host bind mounts (`./mind`, `./state`) need write permission. UID
1000 matches the typical Linux user; on macOS/Docker Desktop the
mount layer translates owners automatically. Without this, volumes
end up root-owned and break the human-editing workflow.

## Why tini

`spawn_sub_agent` spins up subprocesses (cross-model witnesses,
sandboxed code_exec). Without PID 1 zombie reaping, defunct
processes accumulate over long-running compose sessions. tini is
60KB and standard for this pattern.

## What it does NOT do

- **Push images to a registry.** No CI / `docker push` yet. Add when
  needed.
- **Multi-arch builds.** Tested on arm64; amd64 untested in this
  slice.
- **Encrypted volumes / secrets management.** `.env` file is the
  config surface, same as local dev. Production deployments behind
  this should use docker secrets or an external KMS.
- **TLS termination on :8765 / :3000.** Bind is loopback-only by
  default. A reverse proxy (Caddy / nginx) is the right layer for
  TLS; not in this slice.

## Tests

The container shape is validated by `make build` succeeding end-to-end.
Runtime smoke: `make ping` returns `pong` from both providers, and
`docker compose run --rm chimera run "trivial task"` completes a
cycle against the mounted `mind/` and `state/`.

No pytest coverage of the container itself; tests run inside the
local venv (`make test`) and validate the same code that ships in
the image.
