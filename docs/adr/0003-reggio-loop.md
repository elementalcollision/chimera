# ADR 0003 — Reggio Loop Adoption

**Status:** Proposed (recommendation; awaits user mark-up)
**Date:** 2026-05-18
**Context:** Phase 0 follow-up. Closes the "Reggio driving logic" open question raised in [pillar-creativity.md](../research/pillar-creativity.md) and informs [ADR 0001](0001-sdk-chimera-boundaries.md) (loop ownership) and [ADR 0002](0002-memory-strategy.md) (mind/* file hierarchy).

## Context

The Reggio loop in `claude-daemon` is the canonical operational shape of an autonomous Anthropic-tier agent: a fixed-cadence 8-phase heartbeat, side-loop engines tied to time-of-day, a tool-call execution layer with degenerate-loop and write-intent guards, a mutation queue that gates skill activation behind operator approval ("Reggio proposes, the operator disposes"), and a mind/* file hierarchy that doubles as human-readable state and prompt input.

The full Reggio specification supplied by the user describes:

- 8 phases per cycle: **HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE → FLUSH → COMMIT → ROTATE**.
- Plan cadence: Opus invoked every `opus_plan_every_n_cycles` (default 4); other cycles run cheaper daily-rotation engines.
- Daily engines: DiscoveryEngine (08:00 UTC), CuriosityEngine (14:00 UTC), ReflectionEngine (22:00 UTC), ContemplationEngine (rest / T2+ only).
- ACT-phase guards: `tool_loop.detect_degenerate_loop`, `tool_loop.normalize_tool_input`, `task_completion.requires_write_intent` + `extract_target_paths`, PR #58 escalation, PR #54 silent-failure check, Path A3 rewrite.
- TierLadder cost cascade — cheapest rung first, Anthropic safety net.
- Drift assessment in Phase 6 (FLUSH), not in-band per-call.
- Mind file hierarchy (levels 0–5): `HEARTBEAT.md`, `INBOX.md`, `SESSION_LOG.md`, `CHRONICLE.md`, `wiki/projects/*`, plus frontmatter-annotated state.
- 12h session rotation with cycle counter recovered from HEARTBEAT frontmatter.
- Persistence substrate: SQLite (`daemon.db` — `api_calls`, `ladder_outcomes`, sqlite-vec cache) + mind/* markdown + `trust_state.json` + Qdrant sidecar (echoes only, fails open to `[]`).
- Evolution pipeline (continuous side loop): discover → evaluate → assemble → validate → activate, gated by mutation queue.

## Decision (recommendation)

### Loop shape: **8 phases verbatim; side-loop engines deferred**

Chimera adopts Reggio's 8-phase heartbeat as its canonical loop structure in MVP. The Discovery/Curiosity/Reflection/Contemplation engines are **deferred to v1+**.

**Why adopt the phases now:**
- The phase boundaries are where observability, cost discipline, and drift assessment live. Collapsing to a 4-phase loop loses (a) the FLUSH window for drift assessment (would push it in-band), (b) the COMMIT phase's natural git-checkpoint slot, and (c) the ROTATE behavior that gives Chimera bounded-session ergonomics.
- The 8 phases are cheap when most are stubs. HOUSEKEEPING, WAKE, COMMIT, ROTATE can be a few lines each at MVP.
- The phase shape is a stable interface. We can add engine hooks in PLAN later without restructuring callers.

**Why defer the engines:**
- DiscoveryEngine, CuriosityEngine, ReflectionEngine are heavyweight — each is its own LLM-driven sub-loop with prompt templates, slugification rules, idempotency rules, and CHRONICLE-write semantics. They presuppose a populated mind/wiki.
- The engines are tightly coupled to Reggio's specific aesthetic (curiosity sub-modes, wiki projects, ChroniCLE morning/evening sections). Chimera should decide its own aesthetic before importing this layer.
- The MVP value of these engines is unclear without a target user task. Re-evaluate at Phase 4 when adaptability/creativity layers go in.

**Phase-by-phase MVP scope:**

| Phase | MVP behavior | Source pattern |
|---|---|---|
| 0 HOUSEKEEPING | `MutationQueue.sweep_stale()` over the entities table; expire `PENDING` mutations older than N cycles | `daemon.MutationQueue.sweep_stale` |
| 1 WAKE | Read level-0/1 mind files (`HEARTBEAT.md`, `INBOX.md`); zero LLM calls | `MemoryStore.boot_context` |
| 2 ASSESS | Parse `INBOX.md` for `- [ ]` task lines; emit task list with provenance comments | `_phase_assess` |
| 3 PLAN | Every Nth cycle: Opus plan with path-discipline preamble + write-tool allowlist; parse fenced ```tasks blocks; dedup via cluster_key; queue mutations. Off-cycle: stub (no engine swap in MVP) | `StrategyEngine.plan` |
| 4 ACT | Per inbox task: classify → route → `TierLadder.execute()` → up-to-8-round tool loop. Adopt **all** guards: degenerate-loop, normalize_tool_input, requires_write_intent + extract_target_paths, silent_failure check, Path A3 rewrite. Budget tracker raises `CycleBudgetExceeded` at cap. | `_execute_task_with_tools`, `tool_loop.*`, `task_completion.*` |
| 5 WRITE | Update `HEARTBEAT.md` frontmatter; append `SESSION_LOG.md`; auto-mark completed `INBOX.md` items via `write_targets ∩ extracted_paths` | `_phase_write` |
| 6 FLUSH | Context-pressure check; cycle cost/latency summary; `DriftDetector.observe()` and periodic `assess()` (lockdown at composite ≥ 0.30); stale-rung check on TierLadder | `budget.cycle_summary`, `safeguards/drift.py` |
| 7 COMMIT | Git checkpoint if Chimera in T1+ trust; (WikiGenerator deferred) | `git_commit_loop` |
| 8 ROTATE | Wall-clock since session start > `session_max_hours` (default 12h): mark drift boundary, write rotation log, exit cleanly. docker-compose `restart: unless-stopped` recovers. Cycle counter restored from frontmatter | `_rotate_session` |

**Cadence:** default cycle period 15 minutes (Reggio's default). Tunable via `CHIMERA_CYCLE_SECONDS` env var.

### Mind/* hierarchy: **Hybrid**

This is **a delta to [ADR 0002](0002-memory-strategy.md)**. [ADR 0002](./0002-memory-strategy.md) specified SQLite for ontology + activity log + drift state. Reggio's mind/* file model is complementary, not a replacement.

| What | Where | Why |
|---|---|---|
| KFM entities, transitions, authority audit | SQLite (`entities`, `entity_transitions`) per [ADR 0002](./0002-memory-strategy.md) | Relational integrity for KFM check. |
| Activity log (cycle, cell_id PK) | SQLite per [ADR 0002](./0002-memory-strategy.md) | Idempotent claim writes. |
| Drift state snapshots | JSON files (`state/drift/<session>.json`) per [ADR 0002](./0002-memory-strategy.md) | Already a Leonardo-style snapshot. |
| API call ledger, ladder outcomes | SQLite (`api_calls`, `ladder_outcomes`) — **new tables**, [ADR 0002](./0002-memory-strategy.md) amendment | Cost/latency observability; matches Reggio's `daemon.db`. |
| **HEARTBEAT.md** (current cycle, trust tier, model usage frontmatter) | `mind/HEARTBEAT.md` | Human-readable cycle state; the source of truth Chimera resumes from across container restarts. |
| **INBOX.md** (active task list, `- [ ]` / `- [x]`) | `mind/INBOX.md` | Operator-editable. Chimera reads in ASSESS, writes in WRITE. |
| **SESSION_LOG.md** (cycle-by-cycle event log) | `mind/SESSION_LOG.md` | Append-only. Human-tail-able. |
| **CHRONICLE.md** (daily synthesis — deferred until engines land) | `mind/CHRONICLE.md` | Stub at MVP; populated when daily engines arrive. |
| Plans, lessons, project notes | `mind/wiki/**.md` | Long-lived narrative state. |

**Rule:** SQLite is the *index*; mind/* is the *source of truth* for narrative/cycle state. Where the two overlap (e.g. the cycle counter), the mind/* frontmatter wins on read after restart; SQLite is rebuilt on next cycle from mind/*. This matches Reggio's `_restore_cycle_count()` behavior.

**Path layout:**

```
state/                       # docker volume
  chimera.db                 # SQLite (per [ADR 0002](./0002-memory-strategy.md) + api_calls/ladder_outcomes)
  drift/<session>.json
mind/                        # docker volume, human-editable
  HEARTBEAT.md
  INBOX.md
  SESSION_LOG.md
  CHRONICLE.md               # stub at MVP
  wiki/
    plans/
    lessons/
```

### ACT-phase guards: **all adopted at MVP**

Non-negotiable. These are what stop a tool-using agent from going off the rails. Ports of:

- `tool_loop.detect_degenerate_loop` → `chimera/tools/loop_guard.py`
- `tool_loop.normalize_tool_input` → same module (handles OpenRouter's `{"_raw": "..."}` malformed-JSON shape)
- `task_completion.requires_write_intent` + `extract_target_paths` → `chimera/tools/write_intent.py`
- PR #58 escalation (correction prompt + one-tier-up retry on write-intent miss) → `chimera/core/escalation.py`
- PR #54 silent-failure check (zero tools called on write-intent task → mark failed)
- Path A3 rewrite (bare `foo.md` → `mind/foo.md`)

### Mutation queue: **adopted with simplified policy**

Adopt the queue and the "Reggio proposes, operator disposes" gate. **Simplification**: at MVP, the "operator" is the human user via CLI (`chimera mutations list`, `chimera mutations approve <id>`). Auto-activation by trust tier is deferred until trust-tier logic lands.

### TierLadder cost cascade: **adopted; ladder content per [ADR 0001](./0001-sdk-chimera-boundaries.md)**

[ADR 0001](./0001-sdk-chimera-boundaries.md) already committed to Leonardo's `MODEL_TIERS`. Reggio's `TierLadder.execute()` walks cheapest-first with a safety net. Same shape; ladder content already canonicalized. `LadderOutcomeRecorder` tables go into SQLite (`ladder_outcomes`).

### Evolution pipeline (discover → evaluate → assemble → validate → activate): **deferred to v1+**

The full evolution side loop with sandbox subprocess validation is Phase 4-or-later. The mutation queue infrastructure lands in MVP (so the *interface* is stable); the *engines that feed it* come later. This matches the deferral of Discovery/Curiosity/Reflection engines above.

### Indexer sidecar / Qdrant: **NOT in MVP, per [ADR 0002](./0002-memory-strategy.md)**

Echoes are nice but not necessary. [ADR 0002](./0002-memory-strategy.md)'s deferral of Qdrant stands. When/if added, the `IndexerClient.search` failure semantics (0.25s timeout, fails-open to `[]`) are adopted verbatim.

## Consequences

- **`chimera/core/loop.py`** is the 8-phase implementation. Each phase is a method on a `ChimeraLoop` class. Phases are independently testable.
- **`chimera/core/escalation.py`** holds PR #58-style correction prompts.
- **`chimera/tools/loop_guard.py`** and **`chimera/tools/write_intent.py`** are MVP modules.
- **[ADR 0002](./0002-memory-strategy.md) amended** (informally; will be folded into a 0002 revision if needed): adds `api_calls` and `ladder_outcomes` tables; adds the mind/* directory as a peer to `state/`.
- **`PLAN.md` Phase 1 expands**: Task 1.3 (Agent loop v0) becomes "Agent loop with 8 phases, stubs OK"; Task 1.4 (Shell tool) gets companion task 1.4b (ACT-phase guards).
- **No engines at MVP** means the cycle is sparse: PLAN runs Opus every 4th cycle and does nothing otherwise; HOUSEKEEPING/WAKE/COMMIT/ROTATE are minimal. That's fine — the phase boundaries are the value, not the engine fill.
- **The "human-as-operator" model for mutation approval** means MVP Chimera is not fully autonomous; that's a deliberate choice to keep the failure modes small.

## Open Items

1. **Cycle period default** — Reggio uses 15 min. Chimera MVP scope (single-user, no autonomy) might benefit from faster (5 min) or on-demand cycles. Recommend 15 min; revisit when there's actual usage data.
2. **Trust tier system** — Reggio's TrustManager (T0/T1/.../AUTONOMOUS) is referenced by drift lockdown and auto-activation. Chimera MVP can run with a single hardcoded tier; full trust-tier system is its own ADR when needed.
3. **WikiGenerator** — Reggio's COMMIT phase regenerates `/srv/site`. Out of scope for Chimera MVP; the COMMIT phase is just a git checkpoint until/unless a Chimera dashboard appears (PLAN §Phase 5).
4. **Indexer / Qdrant timing** — when does it become worth it? Trigger condition recommendation: when prompt context regularly exceeds 50% of model max and we need to retrieve rather than stuff.

## References

- User-supplied Reggio specification (conversation, 2026-05-18).
- [pillar-creativity.md](../research/pillar-creativity.md) — Patterns 1-4 (proposal bounds, dedup, critic loop, assembly pipeline).
- [pillar-adaptability.md](../research/pillar-adaptability.md) — Patterns 2-4 (history formatting, drift detection, dedup).
- [pillar-ontology-drift.md](../research/pillar-ontology-drift.md) — drift assessment in FLUSH, not in-band.
- [pillar-positioning.md](../research/pillar-positioning.md) — signal handling, rotation, activity log.
- [tool-layer-survey.md](../research/tool-layer-survey.md) — tool registry/dispatch boundary.
- [ADR 0001](0001-sdk-chimera-boundaries.md), [ADR 0002](0002-memory-strategy.md).
