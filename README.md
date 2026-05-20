# Chimera

A multi-LLM, tools-capable agent built on a thin Python core. Pulls patterns
from Hermes, OpenClaw, Reggio (claude-daemon), Leonardo, village (KFM), and
autoresearch — selectively, never wholesale.

**Status:** v4.52 — production-shape with a learning loop. Stable schemas, an
8-phase agent loop, a federation drill, a graph-backed memory, a live
observability dashboard, and persistent task-escalation memory so the agent
learns from its own failures.

## What it does

- Runs an 8-phase cycle: HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE → FLUSH → COMMIT.
- Dispatches tools (shell, code_exec, web_fetch, web_search, MCP peers, sub-agents) **in parallel** within each ACT round.
- Maintains a KFM ontology (entities + transitions) in SQLite and a Kuzu-backed projection for graph queries.
- Auto-archives stale DEPRECATED entities; queues kill-mutations for operator-gated permanent retirement.
- Federates with other Chimera nodes over MCP stdio or HTTP with bearer auth; trust-gated outbound dispatch.
- Surfaces queue health, ontology audit, drift, re-anchor trend, tool fan-out and cost-per-fan-out in a Next.js canvas dashboard.

## Quick start (local)

```bash
# 1. Install (uv-based)
uv sync

# 2. Set provider keys
cp .env.example .env  # then edit
# ANTHROPIC_API_KEY=sk-...
# OPENROUTER_API_KEY=sk-or-...

# 3. Smoke test both providers
set -a; source .env; set +a
uv run chimera ping --provider both
#   [anthropic] reply='pong' finish='end_turn'
#   [openrouter] reply='pong' finish='stop'

# 4. Run one cycle with an ad-hoc task
uv run chimera run "Summarise the top 3 LLM cost-per-token trends of 2026 to mind/cost_report.md"
```

## Docker

```bash
make build          # multi-stage image
make run            # runs `chimera run` against ./mind and ./state
make dashboard      # boots the Next.js control plane (port 3000)
```

See [ADR 0064 — Container bootstrap](docs/adr/0064-container-bootstrap.md) for
the production deployment shape.

## Dashboard

```bash
cd control-plane && npm install && npm run dev
# → http://127.0.0.1:3000
```

Widgets: Status, Token cost, Cost-over-time, Drift composite, Phase timings,
Ontology + Audit, API calls, Mutations + Queue health, Skill assembly,
Skill graph, Fragmentation, Peers, Trust journal, Emergence, Re-anchor
history, **Tool fan-out** (per-model + history + cost-per-tool-call), Inbox,
Chronicle. All reading directly from SQLite. Drag, pin, hide, three-way
theme, four view presets (Operator / Cost / Debug / Federation).

## Architecture

| Layer | Pieces |
|---|---|
| **Loop** | `chimera/core/loop.py` — 8 phases, per-phase budget, activity log |
| **ACT** | `chimera/core/act.py` — parallel tool dispatch, tier escalation (intra- and cross-cycle), continuation-context carry-over, schema-hint on validation error, round-boundary latency telemetry |
| **Learning** | `chimera/core/escalation.py` — persistent `task_escalations` memory: a task that fails at one tier auto-promotes the next attempt; budget scales with tier (v4.47); `chimera escalations list/summary/clear` for operator inspection |
| **Providers** | Anthropic + OpenRouter; tier ladder (haiku → sonnet → opus → cross-provider witnesses); auto-sync prices via `chimera tiers --json` |
| **Tools** | shell, code_exec, http_fetch, web_search, mcp_client, spawn_sub_agent, plus dynamic skills loaded from `chimera/tools/dynamic/` |
| **Memory** | SQLite (entities, transitions, mutations, api_calls, activity log) + Kuzu graph projection (auto-incremental during housekeeping) |
| **A2A** | MCP server (stdio + HTTP/SSE w/ bearer auth), peer registry, trust policy with ALLOW/DEGRADE/REFUSE, protocol journal |
| **Engines** | Discovery / Curiosity / Reflection — chronicle writers + mutation proposers, env-gated kill-switch |
| **Drift** | Composite score with semantic + behavioral + stagnation; demote-plan policy; per-cycle time series |
| **Trust** | T0–T5 ladder with promotion criteria; lockdown via drift threshold |
| **Dashboard** | Next.js 15 + Turbopack + react-grid-layout, MLC design language, 18 widgets |

## Documentation

- **PLAN** — [PLAN.md](PLAN.md)
- **ADRs** — [docs/adr/README.md](docs/adr/README.md) (72 decision records)
- **Research bundle** — [docs/research/best-of-breed.md](docs/research/best-of-breed.md)

## Layout

```
chimera/              # Python package
  core/               # loop, act, kfm, adaptation, drift_log, doctor
  providers/          # anthropic, openrouter, tiers
  tools/              # shell, code_exec, web, mcp_client, subagent, registry, dispatch
  tools/dynamic/      # operator-approved generated skills
  memory/             # sqlite + kuzu graph + audit + mutations
  a2a/                # peer registry, dispatch, trust policy, protocol journal
  server/             # MCP stdio + HTTP server, peer auth
  engines/            # discovery, curiosity, reflection
  scenarios/          # drift, two_chimera, federation drills, graph stress
control-plane/        # Next.js dashboard
mind/                 # narrative state (HEARTBEAT, INBOX, CHRONICLE, wiki)
state/                # SQLite + Kuzu graph + journals (gitignored)
docs/
  adr/                # 72 architecture decision records
  research/           # best-of-breed survey, deliverables
tests/                # 576 passing, 5 skipped
```

## Tests

```bash
uv run pytest -q          # full suite (~10s; 576 passing, 5 skipped)
uv run pytest -m slow     # also runs federation/HTTP drills (~10s extra)
```

## License

MIT — see [LICENSE](LICENSE).
