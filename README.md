# Chimera

A multi-LLM tools-capable agent — a "best-of-breed chimera orchestrator" built on a thin Python core that selectively pulls patterns from Hermes, OpenClaw, Reggio (claude-daemon), Leonardo, village (KFM), and autoresearch.

**Status:** v4.0 — first stable line. Persistent schemas, mind layout, env vars, HTTP endpoints, and CLI verbs are documented in [ADR 0025](docs/adr/0025-v4-stability.md). See [PLAN.md](PLAN.md), [docs/research/best-of-breed.md](docs/research/best-of-breed.md), and all ADRs under [docs/adr/](docs/adr/).

## Quick start

Requires Docker, docker-compose, and a `.env` with `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY`.

```bash
make build
make run ARGS="--help"
```

## Local dev (no Docker)

```bash
make dev
source .venv/bin/activate
chimera --help
```

## Layout

- `chimera/` — Python package (core loop, providers, tools, drift, positioning, prompts, proposals, memory).
- `mind/` — narrative state (HEARTBEAT, INBOX, SESSION_LOG, wiki). Human-editable; the source of truth for cycle state.
- `state/` — SQLite (`chimera.db`) + per-session drift JSON. Gitignored.
- `docs/` — research deliverables and ADRs.
- `research/_clones/` — vendored upstream repos (gitignored; reference only).
