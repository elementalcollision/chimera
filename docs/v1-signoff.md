# Chimera v1 Sign-off

**Status:** Ready for review.
**Date:** 2026-05-18.
**Phase 0 gate doc:** [best-of-breed.md](research/best-of-breed.md).

## What v1 delivers

A containerized, multi-LLM, tools-capable agent with four pillars working
together inside an 8-phase Reggio heartbeat:

| Pillar | Wired into | Evidence in one cycle |
|---|---|---|
| **Adaptability** | system prompt (hardware probe + recent api_call history + composite voice) | every ACT call sees the dynamic prompt |
| **Creativity** | PLAN phase (Opus → fenced ```tasks block → fingerprint+cluster-verb dedup → INBOX append) | `ladder_outcomes.task_type='plan'` row |
| **Ontology + drift** | KFM 7-state machine in SQLite + 3-instrument behavioral drift + stagnation drift + graduated policy | DEPRECATED/STABLE plan entities; drift state JSON |
| **Environmental positioning** | activity_log per phase + drain primitives + circuit breaker + dynamic sensor (load/mem/disk) | 8 `agent_activity_log` rows per cycle |

## What's in the box

**Module layout** (per [ADR 0001](adr/0001-sdk-chimera-boundaries.md)):

```
chimera/
  cli.py                     # status / run / ping / ontology / scenario
  core/
    loop.py                  # 8-phase heartbeat
    act.py                   # tool-using multi-turn executor + ACT guards
    strategy.py              # PLAN-phase Opus planner
    kfm.py                   # pure 7-state KFM machine
    escalation.py            # PR #58 correction prompt
    mind.py                  # HEARTBEAT/INBOX/SESSION_LOG I/O
  providers/
    base.py + anthropic.py + openrouter.py
    messages.py              # rich content-block message model
    tiers.py                 # Leonardo's MODEL_TIERS + tier ladders
  tools/
    registry.py              # Hermes-style register() + TTL check_fn
    dispatch.py              # OpenClaw-style 5-layer policy pipeline
    loop_guard.py            # degenerate-loop + normalize_tool_input
    write_intent.py          # path extraction + Path A3 rewrite
    shell.py                 # strict allow-list shell
    web.py                   # http_fetch + web_search (Exa/Brave/Tavily)
    code_exec.py             # sandboxed python -I subprocess
    mcp_client.py            # stdio MCP client
    subagent.py              # spawn_sub_agent (depth-limited)
  drift/
    behavioral.py            # 3-instrument fallback detector
    stagnation.py            # orthogonal proposal-bucket axis
    policy.py                # {NUDGE, OBSERVE, DEMOTE_PLAN, KILL_SESSION}
  memory/
    store.py                 # SQLite WAL + schema bootstrap
    entities.py              # KFM CRUD + activity_log + api_calls + ladder_outcomes
  prompts/
    voice.py                 # composite Chimera voice
    hardware.py              # static spec probe
    history.py               # recent api_call summary
  positioning/
    drain.py                 # SIGTERM/SIGINT → asyncio.Event
    sensor.py                # dynamic load/mem/disk reading
    circuit.py               # CLOSED/OPEN/HALF_OPEN breaker
  proposals/
    generate.py              # fenced ```tasks parser + plan prompt
    dedup.py                 # fingerprint + cluster_key
  scenarios/
    drift_scenario.py        # Phase 2 checkpoint artifact
    research_scenario.py     # Phase 3 checkpoint artifact
mind/
  HEARTBEAT.md INBOX.md SESSION_LOG.md  # narrative source of truth
state/
  chimera.db drift/*.json    # SQLite + per-session drift snapshots
```

**Persistence (per [ADR 0002](adr/0002-memory-strategy.md) + [ADR 0003](adr/0003-reggio-loop.md) amendment):**

SQLite (`state/chimera.db`) tables: `entities`, `entity_transitions`,
`agent_activity_log`, `api_calls`, `ladder_outcomes`. Mind/* markdown
files are the cycle/narrative source of truth. Drift snapshots are JSON
under `state/drift/`. No vector DB at v1.

**Dependencies (the entire MVP runtime list):**

`anthropic`, `mcp`, `httpx`, `pydantic`, `pyyaml`. Dev: `pytest`,
`pytest-asyncio`, `ruff`, `alembic`. Zero runtime dependence on Hermes,
OpenClaw, Leonardo, Village, autoresearch, or claude-daemon source.

## Verification at v1

- **223 host tests passing** (+1 skipped — `web_search` live test for Tavily, not configured).
- **Live integration tests** for Anthropic + OpenRouter + Exa + Brave.
- **Docker image `chimera:dev` 311MB**, runs the CLI inside the container with mounted `mind/` + `state/` volumes.
- **One real cycle** (cycle 4 with seeded HEARTBEAT) hit every pillar:
  - PLAN — Opus call recorded with `task_type='plan'`
  - ACT — 4 tool-call rounds against the shell tool, task flipped to `[x]`
  - Ontology — STABLE plan entity persisted
  - Activity log — 8 phase rows
  - Drift — observation accumulated, ready to assess
- **Scripted scenarios** working in-container: `chimera scenario drift`, `chimera scenario research`.

## Open items / follow-ups

| Item | Where | When |
|---|---|---|
| Daily engines (Discovery / Curiosity / Reflection / Contemplation) | per [ADR 0003](adr/0003-reggio-loop.md) deferred-list | v1+ |
| Skill assembly pipeline (discover → evaluate → assemble → validate → activate) | per [ADR 0003](adr/0003-reggio-loop.md) | v1+ |
| Cognitive modes + voice polymorphism | inspiration only per user decision | revisit if Phase 4 layer wants it |
| Qdrant / episodic memory | per [ADR 0002](adr/0002-memory-strategy.md), trigger: prompt context regularly >50% of model max | when needed |
| Postgres migration | per [ADR 0002](adr/0002-memory-strategy.md), trigger: multi-container concurrency or ~10M activity rows | when needed |
| Tighter PLAN prompt — Opus emitted reasoning that hit 1024-tok cap on first run; bumped default to 4096 | `chimera/core/strategy.py` | already done |
| `anthropic/claude-*` mirror IDs on OpenRouter | TODO in [tiers.py](../chimera/providers/tiers.py) | when Anthropic-via-OpenRouter routing is needed |
| Network egress isolation for `code_exec` | TODO in [code_exec.py](../chimera/tools/code_exec.py) | follow-up ADR |
| Trust-tier system + Steiner auto-promotion | not started | when autonomy needs gating |
| Xenocomm / A2A integration | per [ADR 0001](adr/0001-sdk-chimera-boundaries.md) | v2 |
| TS control plane / dashboard | per [PLAN.md](../PLAN.md) Phase 5 | post-v1 |

## How to sign off

1. `make build` — builds `chimera:dev`.
2. `docker compose run --rm chimera ping` — verifies provider keys.
3. `docker compose run --rm chimera scenario drift` — verifies KFM + drift end-to-end.
4. `docker compose run --rm chimera scenario research` — verifies ACT + tools end-to-end.
5. `make test` (or `uv run pytest`) — full host suite.
6. Read this doc plus the Phase 0 gate doc and the three core ADRs.

When you say "v1 signed off", I'll mark Phase 4 checkpoint complete and we either ship or plan v1.x.
