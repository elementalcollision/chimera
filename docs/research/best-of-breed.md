# Chimera — Best-of-Breed Synthesis

**Status:** Phase 0 gate document. Sign-off required before Phase 1 code lands.
**Date:** 2026-05-18
**Closes:** Task 0.9. Synthesizes Phase 0 research deliverables and the three ADRs into a single overview.

---

## Purpose

This is the **one-page contract** for Chimera v1: what we adopt, from where, and why. It does not restate the deep docs — it points to them and surfaces the decisions that bind Phase 1+ work.

## Reading order for sign-off

| # | Doc | What it gives you |
|---|---|---|
| 1 | This file | Decisions overview, gate checklist |
| 2 | [PLAN.md](../../PLAN.md) | Phase breakdown, source repos, risks |
| 3 | [ADR 0001](../adr/0001-sdk-chimera-boundaries.md) | Per-concern ownership: who owns what code |
| 4 | [ADR 0002](../adr/0002-memory-strategy.md) | Persistence strategy: SQLite + mind/* + drift JSON |
| 5 | [ADR 0003](../adr/0003-reggio-loop.md) | The 8-phase Reggio loop as Chimera's canonical heartbeat |
| 6 | [pillar-ontology-drift.md](pillar-ontology-drift.md) | KFM 7-state machine + dual drift detectors |
| 7 | [pillar-positioning.md](pillar-positioning.md) | Activity log, drain, circuit breakers, skip-memo |
| 8 | [pillar-creativity.md](pillar-creativity.md) | Bounded proposals, semantic dedup, critic loop |
| 9 | [pillar-adaptability.md](pillar-adaptability.md) | Hardware-aware prompts, history formatting, stagnation detection |
| 10 | [tool-layer-survey.md](tool-layer-survey.md) | Hermes registry + OpenClaw policy pipeline |
| 11 | [repo-index.md](repo-index.md) | One-paragraph characterization of each source repo |

## The architecture in one diagram (text form)

```
                ┌──────────────────────────────────────────────────────┐
                │                  Chimera (Python core)                │
                │                                                        │
                │   ┌───────────────────────────────────────────────┐  │
                │   │           8-phase Reggio loop (ADR 0003)        │  │
                │   │  HOUSEKEEPING→WAKE→ASSESS→PLAN→ACT→WRITE→FLUSH │  │
                │   │  →COMMIT→ROTATE                                  │  │
                │   └─────────────┬───────────────────────────────────┘  │
                │                 │                                       │
                │       ┌─────────┴─────────┐                            │
                │       │                   │                             │
                │   ┌───▼────┐         ┌────▼─────────────────────┐     │
                │   │PROVIDER│         │   TOOL DISPATCH (ADR 0001) │     │
                │   │ tiers  │         │ Hermes registry + OpenClaw │     │
                │   │(L'rdo) │         │  policy + ACT guards       │     │
                │   └───┬────┘         └────┬─────────────────────┘     │
                │       │                   │                             │
                │  Anthropic/           Shell→Web→CodeExec→MCP            │
                │  OpenRouter           (concentric expansion)            │
                │                                                          │
                │   ┌──────────────────────────────────────────────────┐ │
                │   │      DRIFT (ADR 0001 fallback-only)               │ │
                │   │ behavioral (Leonardo) + stagnation (autoresearch) │ │
                │   │  → policy → {NUDGE, OBSERVE, DEMOTE, KILL}        │ │
                │   └──────────────────────────────────────────────────┘ │
                │                                                          │
                │   ┌──────────────────────────────────────────────────┐ │
                │   │       ONTOLOGY (village/KFM, ADR 0002)            │ │
                │   │ NEW→EXPERIMENTAL→CANDIDATE→STABLE→DEPRECATED      │ │
                │   │ →ARCHIVED→KILLED   (F/M/K operator-typed)         │ │
                │   └──────────────────────────────────────────────────┘ │
                │                                                          │
                │   ┌──────────────────────────────────────────────────┐ │
                │   │   POSITIONING (village)                           │ │
                │   │ activity log heartbeat + drain + circuit-breaker  │ │
                │   └──────────────────────────────────────────────────┘ │
                └──────────────────────────────────────────────────────────┘
                                          │
                            docker volume │ ./state, ./mind
                                          ▼
                          ┌──────────────────────────────┐
                          │ state/chimera.db (SQLite)     │
                          │ state/drift/<sess>.json       │
                          │ mind/HEARTBEAT.md             │
                          │ mind/INBOX.md                 │
                          │ mind/SESSION_LOG.md           │
                          │ mind/wiki/                    │
                          └──────────────────────────────┘
```

## The decisions, by pillar

### Pillar 1 — Adaptability ([pillar-adaptability.md](pillar-adaptability.md))

**Adopt** (autoresearch-unified):
- Environment-aware dynamic system prompt — `hardware.py`-style probe injecting facts into the base prompt.
- History formatting with strategy classification — `format_history_for_prompt()` + auto-categorization.
- Stagnation drift detector — `_detect_stagnation()` heuristic, returns nudge string for prompt injection.
- Near-duplicate detection + re-query — fingerprint + (param, value) regex.

**Reject:** dataset-boundary baseline reset (cross-task concern, not within-task); heartbeat status file (orthogonal — Chimera uses activity log instead).

### Pillar 2 — Creativity ([pillar-creativity.md](pillar-creativity.md))

**Adopt** (claude-daemon):
- Bounded divergent generation — `MAX_PROPOSED_TASKS_PER_PLAN = 3`.
- Semantic deduplication — fingerprint + cluster-verb normalization.
- Critic loop — Opus evaluation gates Sonnet assembly gates sandbox validation.
- Skill assembly pipeline — discover → evaluate → assemble → validate → activate (**v1+, not MVP** per ADR 0003).

**Inspiration only** (Leonardo, per user decision):
- 6 cognitive modes, 13-voice polymorphism, Vitruvian gap-mapping. Chimera has its own composite voice; not adopted as a runtime in v1.

### Pillar 3 — Functional Ontology + Drift ([pillar-ontology-drift.md](pillar-ontology-drift.md))

**Adopt** (village + Leonardo + autoresearch):
- KFM 7-state machine with table-driven authority — port of `village/services/clerk/src/clerk/kfm.py`.
- Multi-instrument behavioral drift (Leonardo `safeguards/drift.py`) — **fallback-only path** per user decision.
- Stagnation drift (autoresearch `_detect_stagnation`) — orthogonal axis.
- Graduated drift response — `{NUDGE, OBSERVE, DEMOTE_PLAN, KILL_SESSION}`, KFM-aware.

**F/M/K operators:** single orchestrator with role-typed methods (not separate processes), per user decision. Revisit at Xenocomm/A2A time.

**Defer:** Croissant as serialization layer (evaluate when ontology schema firms up, possibly v1+ export).

### Pillar 4 — Environmental Positioning ([pillar-positioning.md](pillar-positioning.md))

**Adopt** (village):
- Activity log as primary heartbeat — `(cycle, cell_id)` PK for idempotent claims.
- SIGTERM/SIGINT → `asyncio.Event` drain with 30s timeout.
- Circuit breakers (CLOSED/OPEN/HALF_OPEN) on every peer call, exposed on `/health`.
- Skip-memo cooldown for capability rejections (~30s TTL).

**Rethink at scale:** Clerk-as-synchronous-SoT, pull-model activity polling, per-building isolation. Recommendations in pillar doc; not MVP concerns.

### Tool layer ([tool-layer-survey.md](tool-layer-survey.md))

**Adopt:**
- Hermes-style registry: `registry.register(name, toolset, schema, handler, check_fn, ...)`, AST auto-discovery, TTL-cached `check_fn`.
- OpenClaw-style multi-layer policy pipeline applied **pre-dispatch**.
- Reggio ACT-phase guards: degenerate-loop, normalize_tool_input, write-intent enforcement, PR #58 escalation, PR #54 silent-failure, Path A3 rewrite.
- Concentric sandbox expansion — shell → web → code exec → MCP.

**Re-implement, not depend:** no Hermes or OpenClaw runtime dependencies. Pattern adoption only.

### Loop shape ([ADR 0003](../adr/0003-reggio-loop.md))

**Adopt:** 8-phase Reggio loop verbatim. Side-loop engines (Discovery/Curiosity/Reflection/Contemplation) deferred to v1+. WikiGenerator deferred. Mutation queue lands at MVP with human-as-operator.

### Memory & persistence ([ADR 0002](../adr/0002-memory-strategy.md) + ADR 0003 delta)

- **SQLite** as ontology + activity + api_calls + ladder_outcomes index.
- **mind/* markdown files** as narrative source of truth (HEARTBEAT, INBOX, SESSION_LOG, wiki/).
- **JSON drift snapshots** per session (`state/drift/<session>.json`).
- **No Qdrant, no Postgres, no Croissant, no claude-mem** at MVP. Each has a documented trigger condition for v1+.

## Dependencies (the entire MVP runtime list)

Per ADR 0001:
- `anthropic` — Anthropic Python SDK
- `mcp` — official MCP Python SDK
- `httpx` — for OpenRouter
- `pydantic` v2
- `pytest` (dev)
- `alembic` (dev — migrations)
- Standard library (`asyncio`, `sqlite3`, `dataclasses`, `pathlib`, `signal`, `json`, `re`)

**Not depended on:** Hermes, OpenClaw, Leonardo, Village, autoresearch, claude-daemon, drift-monitor, Qdrant, Postgres, Croissant, claude-mem, xenocomm_sdk, langchain, langgraph, llamaindex.

## Open items carried forward (not gate-blocking)

| # | Item | When it must be resolved |
|---|---|---|
| 1 | Cycle period (default 15 min vs 5 min for interactive use) | Phase 1 |
| 2 | Trust-tier system (Leonardo's T0/T1/.../AUTONOMOUS) | Phase 2 once drift lockdown logic lands |
| 3 | Sub-agent spawn semantics — tool-policy inheritance contract | Phase 3 Task 3.4 |
| 4 | Sandbox elevation mechanism beyond MVP allow-list | Phase 3 Task 3.2 (code exec) |
| 5 | When to add Qdrant (trigger: prompt context regularly > 50% of model max) | Phase 4+ |
| 6 | When to migrate SQLite → Postgres (trigger: cross-container concurrency or ~10M activity-log rows) | v1+ |
| 7 | Cognitive modes / voice polymorphism — revisit as inspiration when adapting Phase 4 creativity layer | Phase 4 |
| 8 | Xenocomm / A2A integration | Phase 5 / v2 |

## Phase 0 sign-off gate

Confirm before Phase 1 (skeleton + container + Anthropic loop + shell tool) begins:

- [ ] **Reading complete** — you've read this file plus the three ADRs.
- [ ] **The five pillar docs are accurate enough** — no factual errors in source citations; corrections welcome but not required to be exhaustive.
- [ ] **Per-concern ownership in ADR 0001** is the right cut of the chimera.
- [ ] **Memory strategy in ADR 0002** is acceptable for MVP (SQLite + mind/* + JSON drift; no vector DB).
- [ ] **Reggio loop adoption in ADR 0003** is acceptable (8 phases, no engines at MVP, mutation-queue gate, human-as-operator).
- [ ] **Dependencies list above** is complete; no surprise additions before Phase 1.
- [ ] **Open items 1–8** are correctly deferred — not silently dropped.

When you say "Phase 0 signed off," I'll mark Task 0.9 complete and begin Task 1.1 (repo + Docker scaffold).
