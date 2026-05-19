# ADR 0002 — Memory Strategy

**Status:** Accepted (pending Phase 0 sign-off)
**Date:** 2026-05-18
**Context:** Phase 0 Research Spike — closes Task 0.8. Depends on [ADR 0001](0001-sdk-chimera-boundaries.md) and [pillar-ontology-drift.md](../research/pillar-ontology-drift.md).

## Context

Memory in Chimera spans four conceptually distinct stores:

1. **Ontology state** — KFM lifecycle records for every agentic entity (skills, tools, plans, sub-agents). Atomic per-transition. Strict relational integrity. Auditable trail.
2. **Activity log** — proof-of-work heartbeat from the agent loop. Append-only, high write rate (10–100/sec at peak), queried in cycle-bounded windows.
3. **Drift state** — vocabulary sets, tool-call distributions, semantic anchors. Per-session snapshots; reset on `mark_boundary()`.
4. **Episodic / semantic recall** — past plans, lessons, retrieved evidence. Embedding-friendly. Read-heavy. Optional in MVP.

The Phase 0 ontology shape (per [pillar-ontology-drift.md Pattern 1](../research/pillar-ontology-drift.md)) is **strongly relational**: a 7-state machine with table-driven authority. That biases stores (1) and (2) toward SQL. Store (3) is per-session ephemeral with a small persisted snapshot. Store (4) is the only candidate that genuinely wants vector search.

User-set constraints:
- Docker + docker-compose runtime, single-user MVP.
- OpenRouter + Anthropic only; no embedding model wired yet.
- `drift-monitor` library is fallback-only — so the full `SemanticDrift` embedding path is not active at MVP.
- Croissant evaluated but not assumed.

## Decision

### MVP (Phase 1–2)

| Store | Backend | Why |
|---|---|---|
| Ontology state (KFM records, transitions, authority audit) | **SQLite** (`chimera.db`, WAL mode, single file mounted into the container) | Matches village's relational KFM model directly. ACID. Zero ops cost. Easy to inspect with `sqlite3 chimera.db`. |
| Activity log | **SQLite, same DB, separate table `agent_activity_log`** with PK `(cycle, cell_id)` for idempotent claim writes | Mirrors village's schema (`research/_clones/village/services/clerk/alembic/versions/0004_agent_activity_log.py`). At MVP scale (single agent, ~10 writes/sec), SQLite WAL handles it comfortably. |
| Drift state (behavioral fallback path) | **JSON snapshot file per session** under `state/drift/<session_id>.json` | Matches `safeguards/drift.py:_load_state()` / `_save_state()`. Survives container restarts. Small (~KB). |
| Episodic / semantic recall | **DEFERRED** — not in MVP scope | No embedding model active; no use case yet. |

### Schema (initial)

```sql
-- Ontology
CREATE TABLE entities (
  id TEXT PRIMARY KEY,             -- UUID
  kind TEXT NOT NULL,              -- skill | tool | plan | subagent
  name TEXT NOT NULL,
  kfm_state TEXT NOT NULL,         -- KFM_STATES enum
  state_entered_at_cycle INTEGER NOT NULL,
  details JSON,                    -- arbitrary per-kind payload
  created_at TEXT NOT NULL,
  UNIQUE(kind, name)
);

CREATE TABLE entity_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  operator_type TEXT NOT NULL,     -- f | m | k | bootstrap
  reason TEXT,
  cycle INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_transitions_entity ON entity_transitions(entity_id, cycle);

-- Activity log
CREATE TABLE agent_activity_log (
  cycle INTEGER NOT NULL,
  cell_id TEXT NOT NULL,           -- routing/partition key
  agent_id TEXT NOT NULL,
  activity_type TEXT NOT NULL,
  layer TEXT,
  cell_ref TEXT,
  details JSON,
  created_at TEXT NOT NULL,
  PRIMARY KEY (cycle, cell_id)     -- idempotent claim
);
CREATE INDEX idx_activity_agent_cycle ON agent_activity_log(agent_id, cycle);
```

Migrations via **Alembic** (matches village's tooling), so the path from SQLite → Postgres at v1+ is a connection-string change plus dialect-specific tweaks.

### Drift-state file layout

```
state/
  drift/
    <session_id>.json   # { vocab: [...], tool_counts: {...}, anchor_vocab: [...], anchor_tool_counts: {...} }
```

Persistence is `safeguards/drift.py`-compatible so the upgrade path to the full `drift-monitor` library doesn't require a schema migration.

### v1+ (after MVP)

- **Promote SQLite → Postgres** when (a) we need cross-container concurrency, (b) the activity log exceeds ~10M rows, or (c) we want LISTEN/NOTIFY for event-driven operators. Alembic migrations make this routine.
- **Add Qdrant** *only* when an episodic/semantic recall feature has a concrete acceptance criterion (e.g., "the agent must retrieve past lessons relevant to the current plan"). Until then, the absence of embeddings is a feature: no embedding cost, no embedding-drift concern, no model coupling.
- **Re-evaluate Croissant** as a serialization layer for the ontology — but only as an export format (`chimera ontology export --format=croissant`), not the primary store. JSON-LD's strengths (lineage, provenance) are real, but they don't outweigh SQLite's local-ops simplicity.
- **claude-mem integration** — out of scope for v1. Re-evaluate at the same time as episodic recall.

## Rationale (why not the alternatives)

| Option | Why not (at MVP) |
|---|---|
| Qdrant-only | No active use case; embeddings not wired; ops cost (separate container, persistence volume) for zero MVP benefit. |
| Postgres + pgvector | Premature. Adds an ops surface (init scripts, volumes, connection pooling) for a single-user single-agent MVP. Migration path is open. |
| claude-mem (episodic) + Qdrant | Layers two storage systems before there's a use case. Defers decisions about what episodic structure means in Chimera. |
| Croissant as primary store | Schema is dataset-centric; runtime/operational semantics (KFM transitions, activity claims) don't fit cleanly. Good *export* format, wrong *primary* format. |
| Pure JSON files | No relational integrity for KFM authority checks. No indexing for activity-log queries. Doesn't survive concurrent writes. |

## Consequences

- **Single SQLite file** is the canonical Chimera state. Mounted as a docker volume (`./state:/state` in compose). Backed up with `sqlite3 .backup`.
- **Alembic** is added as a dev dependency for migrations. First migration creates the schema above.
- **No vector DB** in MVP. No embedding API calls. No embedding-related drift signal.
- **Drift state files** live under `state/drift/` and rotate per session — no growth concern.
- **Schema is village-shaped** so any future cross-pollination (e.g., importing village's M-Operator probe logic) is a copy, not a translation.
- **Migration to Postgres is a Phase 3-or-later concern** with a clear trigger condition; not a "we'll do it eventually" hand-wave.

## Open Items

1. **Backup/restore policy** — `sqlite3 .backup` nightly is the natural default; codify when we have ops requirements.
2. **State volume size budget** — set a soft cap (e.g., 1 GB) and a GC sweep for the activity log (drop rows older than N cycles).
3. **Session identifier scheme** — UUIDv7 (time-ordered) is the default unless there's a reason otherwise.

## References

- [pillar-ontology-drift.md](../research/pillar-ontology-drift.md) — KFM ontology shape that motivated relational-first.
- [pillar-positioning.md](../research/pillar-positioning.md) — activity-log-as-heartbeat pattern.
- `research/_clones/village/services/clerk/alembic/versions/0004_agent_activity_log.py` — schema reference.
- `Claude_Primary/leonardo/leonardo-daemon/safeguards/drift.py:_load_state()/_save_state()` — drift-state persistence reference.
