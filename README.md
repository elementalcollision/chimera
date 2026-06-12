# Chimera

A multi-LLM, tools-capable agent built on a thin Python core. Pulls patterns
from Hermes, OpenClaw, Reggio (claude-daemon), Leonardo, village (KFM), and
autoresearch — selectively, never wholesale.

**Status:** v4.120 — production-shape with a learning loop, three-layer
cost-discipline, opt-in graph projection, FTS5 wiki recall, a task
splitter, semantic tool/model routing (lexical v0), entropy-governed
sub-tasking (ADRs 0167–0172), model-backed peers, and a hardened
security baseline (ADR 0175: timing-safe peer auth, secret-free tool
subprocesses, atomic trust state). Stable schemas, an 8-phase agent
loop, a federation drill, a live observability dashboard, persistent
task-escalation memory, three orthogonal cost caps (per-cycle /
rolling-hour / per-task) so runaways stop themselves, and a central
flag registry whose combination matrix is CI-enforced (ADR 0176).

## What it does

- Runs an 8-phase cycle: HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE → FLUSH → COMMIT.
- Dispatches tools (shell, code_exec, web_fetch, web_search, **mind_search**, MCP peers, sub-agents) **in parallel** within each ACT round.
- Maintains a KFM ontology (entities + transitions) in SQLite. Kuzu graph projection is **opt-in** (`CHIMERA_GRAPH_ENABLED=1`) — the SQLite + recursive-CTE path covers ~95% of queries.
- Searches its own knowledge base via SQLite FTS5 over `mind/wiki/` before falling back to web_search.
- Auto-archives stale DEPRECATED entities; queues kill-mutations for operator-gated permanent retirement.
- **Three cost caps** (ADRs 0072/0076/0079) hard-stop runaway cycles, slow burns, and stuck tasks; **cost-rate alarm widget + `chimera cost` / `chimera estimate` CLI** for retrospective + prospective visibility.
- Federates with other Chimera nodes over MCP stdio or HTTP with bearer auth; trust-gated outbound dispatch.
- Surfaces queue health, ontology audit, drift, re-anchor trend, tool fan-out, cost-per-fan-out, **cost-rate band**, and engine telemetry in a Next.js canvas dashboard.

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

The default view is **Review** (ADR 0182) — an operator-first surface that
answers the three daily-production questions at a glance: **Production
health** (a worst-of verdict over cost rate, drift, queue staleness,
fragmentation, hot signatures, and ontology audit), what Chimera did
(Chronicle), and what's queued (Inbox + Mutations). The full telemetry
canvas — 25 widgets across the Operator / Cost / Debug / Federation presets
(Status, Token cost, Cost-over-time, Drift composite, Phase timings,
Ontology + Audit, API calls, Mutations + Queue health, Skill assembly,
Skill graph, Fragmentation, Peers, Trust journal, Emergence, Re-anchor
history, **Tool fan-out**, …) — is one click away. All reading directly
from SQLite. Drag, pin, hide, three-way theme.

## Architecture

| Layer | Pieces |
|---|---|
| **Loop** | `chimera/core/loop.py` — 8 phases, per-phase budget, activity log |
| **ACT** | `chimera/core/act.py` — parallel tool dispatch, tier escalation (intra- and cross-cycle), continuation-context carry-over, schema-hint on validation error, round-boundary latency telemetry, three cost caps |
| **Learning** | `chimera/core/escalation.py` — persistent `task_escalations` memory: a task that fails at one tier auto-promotes the next attempt; budget scales with tier (v4.47); research-task tier floor (v4.56); hot-signature alarm (v4.54); `chimera escalations list/summary/clear` |
| **Cost discipline** | `chimera/core/budget.py` — per-cycle, rolling-60m, and per-task caps (v4.53/0072 + v4.57/0076 + v4.60/0079); `chimera cost` retrospective + `chimera estimate` prospective CLI verbs |
| **Providers** | Anthropic + OpenRouter; tier ladder (haiku → sonnet → opus); v4.53 ladder inversion → opus tier defaults to deepseek-v4-pro (34× cheaper); cross-provider witnesses; `chimera tiers --json` price sync |
| **Tools** | shell, code_exec, http_fetch, web_search, **mind_search** (FTS5), mcp_client, spawn_sub_agent, plus dynamic skills loaded from `chimera/tools/dynamic/` |
| **Memory** | SQLite (entities, transitions, mutations, api_calls, activity log, task_escalations, wiki_fts) + opt-in Kuzu graph projection (`CHIMERA_GRAPH_ENABLED=1`) |
| **Task shape** | Heuristic splitter (`chimera split`) detects multi-section / fanout shapes; research-tier floor; per-task budget |
| **A2A** | MCP server (stdio + HTTP/SSE w/ bearer auth), peer registry, trust policy with ALLOW/DEGRADE/REFUSE, protocol journal |
| **Engines** | Discovery / Curiosity / Reflection — chronicle writers + mutation proposers, env-gated kill-switch |
| **Drift** | Composite score with semantic + behavioral + stagnation; demote-plan policy; per-cycle time series |
| **Trust** | T0–T5 ladder with promotion criteria; lockdown via drift threshold |
| **Dashboard** | Next.js 15 + Turbopack + react-grid-layout, MLC design language; operator-first **Review** default (ADR 0182) over 25 widgets / 5 presets |

## Documentation

- **PLAN** — [PLAN.md](PLAN.md)
- **ADRs** — [docs/adr/README.md](docs/adr/README.md) (175 decision records)
- **Operator runbook** — [docs/runbook.md](docs/runbook.md) — three modes, dashboard widget guide, cost CLI, task splitter, escalations
- **AI-helper orientation** — [AGENTS.md](AGENTS.md) — for AI assistants editing this repo
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
  adr/                # 175 architecture decision records
  research/           # best-of-breed survey, deliverables
  runbook.md          # operator runbook
tests/                # 2,494 passing, 5 skipped
```

## Tests

```bash
uv run pytest -q          # full suite (~95s; 2,494 passing, 5 skipped)
uv run pytest -m slow     # also runs federation/HTTP drills (~10s extra)
```

## License

MIT — see [LICENSE](LICENSE).
