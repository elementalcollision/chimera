# AGENTS.md — Orientation for AI helpers working in this repo

If you're an AI assistant (Claude Code, Codex, Cursor, …) editing
this codebase, read this first. It saves you ~30 minutes of
re-discovering conventions the human has already settled.

## What this repo is

Chimera — a multi-LLM tools-capable agent (Python core + Next.js
dashboard). v4.52. Production-shape. See [README.md](README.md) for
the user-facing description; this file is for AI helpers.

## The shape of work here

- **Every behaviour change ships with an ADR** in
  [docs/adr/](docs/adr/). The numbering is contiguous (0001 … 0071).
  Use [docs/adr/0000-template.md](docs/adr/0000-template.md) to start
  a new one. Don't skip this step — the ADR catches design rationale
  that diffs alone destroy.
- **Tests live in [tests/](tests/)**. The suite is around 576/5 with
  good coverage on ACT, escalation memory, federation drills, and
  the graph store. Don't ship Python behaviour changes without
  pinning a test.
- **Versions bump in lockstep** in [pyproject.toml](pyproject.toml)
  and [control-plane/package.json](control-plane/package.json).
  Skipping one will surprise the operator.

## The 8-phase loop is the central abstraction

```
HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE → FLUSH → COMMIT
```

When you're adding state, ask: which phase owns this write? When
you're adding telemetry, ask: which phase's activity row carries it?
See [chimera/core/loop.py](chimera/core/loop.py) — phases are
budgeted in milliseconds and the budget is real (PLAN/ACT get 240k
ms each, everything else ≤ 2k ms).

## What's safe to touch when

| Editing this | Safe during a live `chimera run` cycle? |
|---|---|
| `chimera/*.py` (core, tools, memory) | **No.** Every `uv run chimera` rebuilds the package. Race-condition risk. |
| `tests/*.py` (writing only) | Yes. Tests don't ship with the agent. |
| `tests/*.py` (running `pytest`) | **No.** `pytest` also goes through `uv run`. |
| `docs/`, `README.md`, ADRs | Yes. Pure markdown; no impact on the agent. |
| `control-plane/` | Yes. Next.js is a separate process. |
| `Dockerfile`, `docker-compose.yml`, `Makefile` | Yes. Affects the container, not the live local agent. |
| `mind/INBOX.md`, `mind/HEARTBEAT.md` | **Read-only during run.** The agent owns these. |

When unsure: run `ls /tmp/chimera-longrun/ 2>/dev/null` — if it
exists, a long-horizon run is in flight. Stick to docs.

## Naming & conventions

- **ADR titles** start with the version that introduces the change:
  `# ADR 00NN — Title (v4.M)`. The `(v4.M)` token is searchable.
- **Inline ADR refs** in markdown use the link form `[ADR
  NNNN](./00NN-kebab.md)`. Bare "ADR 0042" is fine in docstrings
  where links don't render, but linkify in prose.
- **Schema migrations** are *additive only* unless ADR 0025 stability
  is explicitly broken. New columns use `try: ALTER TABLE ... ADD
  COLUMN ... except sqlite3.OperationalError: pass` for
  idempotency. See [chimera/memory/store.py](chimera/memory/store.py)
  for the canonical migration site.
- **Tests use the existing fixtures** in `tests/conftest.py` and
  per-file fixtures like `shell_env`, `db`, `dispatcher`. Don't
  reinvent.
- **Storage version bumps** when the canvas widget set or dashboard
  layout changes: increment `STORAGE_LAYOUT` + `STORAGE_PINS` in
  [control-plane/components/CanvasShell.tsx](control-plane/components/CanvasShell.tsx).
  We're currently at v13.

## Tool surface (what the agent itself can call)

The agent's tool ring is:

| Tool | Purpose | Key arg |
|---|---|---|
| `shell` | Subprocess in mind/state allow-list | `argv` (list) |
| `code_exec` | Python in a sandbox | `code` (string) |
| `http_fetch` | HTTP GET with size cap | `url` |
| `web_search` | Search engine query | `query` |
| `spawn_sub_agent` | Recursive ACT with a brief | `brief` |
| `mcp-<peer>-<tool>` | Peer MCP call (trust-gated) | per-tool |

Schemas live in `chimera/tools/*.py`. When a tool call goes through
`Dispatcher.dispatch`, **any `ValueError | TypeError | KeyError`
gets a schema hint appended to the error message** the model sees —
that's the v4.41 feedback loop. Don't strip those hints.

## Common failure modes you may encounter

- **Hot rebuild collision**: two `uv run` commands at once.
  Symptoms: `Building chimera` log line twice, one wins. Mitigation:
  serialise. The Makefile's `make test` and `make cycle` are safe.
- **macOS Kuzu single-file DB**: `state/chimera.graph` is a *file*
  not a directory on newer Kuzu. Anything writing into
  `<graph_path>/.*` will hit `FileExistsError`. Use a sibling
  sidecar: `<graph_path>.something`. See [ADR 0069](docs/adr/0069-round-boundary-instrumentation.md)
  and [ADR 0070](docs/adr/0070-model-utilization-widget.md) for the
  fingerprint sidecar fix.
- **Long file previews truncate model context**: see
  [ADR 0063](docs/adr/0063-continuation-context.md) — files ≥ 2KB
  show head + tail in continuation context, not head-only. Don't
  revert to head-only.
- **Hyphenated peer names + trust gate**: see
  [ADR 0049](docs/adr/0049-hyphenated-peer-names.md). The resolver
  needs the registry to do longest-prefix matching. Don't strip the
  `registry=` kwarg from `peer_name_from_tool`.

## How to read the dashboard

```bash
cd control-plane && npm run dev  # → http://127.0.0.1:3000
```

Widgets are SSR React reading directly from `state/chimera.db`. The
canvas layout persists in localStorage under
`chimera-canvas-layout-v13`. If a widget looks misplaced, hit
**Reset** in the top bar. Each widget has a corresponding reader in
[control-plane/lib/db.ts](control-plane/lib/db.ts).

## Quick orientation

| Surface | Where |
|---|---|
| Agent loop | [chimera/core/loop.py](chimera/core/loop.py) |
| Tool dispatch + policy pipeline | [chimera/tools/dispatch.py](chimera/tools/dispatch.py) |
| Provider abstraction | [chimera/providers/](chimera/providers/) |
| SQLite schema | [chimera/memory/store.py](chimera/memory/store.py) |
| Kuzu graph projection | [chimera/memory/graph.py](chimera/memory/graph.py) |
| Federation drills | [chimera/scenarios/federation_drill.py](chimera/scenarios/federation_drill.py) |
| Dashboard | [control-plane/app/page.tsx](control-plane/app/page.tsx) |
| ADR index | [docs/adr/README.md](docs/adr/README.md) |

## If you only do one thing

Write the ADR before the code. We've held this discipline through
72 ADRs; please don't break it.
