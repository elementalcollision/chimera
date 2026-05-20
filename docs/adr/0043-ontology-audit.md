# ADR 0043 — Memory / ontology audit (v4.21)

**Status:** Accepted (2026-05-19)

## Context

Chimera's KFM ontology accumulates entities (plans, skills, tools,
sub-agents) every cycle, with transitions logged to `entity_transitions`
and proof-of-work to `agent_activity_log`. Until now the only way to
answer "what does Chimera actually remember?" was raw SQL. We had no
view of:

- entities stuck in a non-terminal state for too many cycles,
- entities with zero recent activity (effectively dead),
- whether the drift-policy re-anchor path is firing at all,
- how many DEPRECATED entities are accumulating without being
  archived.

This blocks the v4.21 audit goal: confirm re-anchoring works on a
real corpus, and surface dead memory.

## Decision

Pure read-only audit primitive in `chimera/memory/audit.py`:

```python
def audit_ontology(
    conn,
    *,
    current_cycle: int,
    stale_after_cycles: int = 20,
    activity_window_cycles: int = 10,
    reanchor_window_cycles: int = 50,
    max_listed: int = 20,
) -> dict[str, Any]
```

Returns a single dict:

- `total_entities`, `by_kind`, `by_state` (counts)
- `stale_entities` (with `cycles_in_state`)
- `dead_entities` (no activity_log row in the recent window, joined
  via `cell_ref = entity_id`)
- `deprecated_unarchived` count
- `reanchor_events_in_window` — count of `STABLE → DEPRECATED`
  transitions written by the K-operator (the drift-policy demotion
  path). This is the metric that confirms re-anchoring is firing in
  production.

Terminal states (`ARCHIVED`, `KILLED`) are excluded from stale/dead.

### CLI

`chimera ontology --audit [--cycle N] [--stale-after-cycles 20] [--json]`

- `--cycle` defaults to `MAX(cycle)` from the activity log.
- Non-JSON output prints the snapshot with grouped sections.

## Tests

`tests/test_audit_ontology.py`:

- empty DB → all zeros
- stale entity flagged with correct cycles_in_state
- dead entity flagged when activity log empty
- terminal-state walks (NEW → ARCHIVED) NOT flagged
- two K-operator demotions counted via `reanchor_events_in_window`
- by_kind / by_state aggregation

Full suite: 515 passing, 5 skipped (+6 new).

## Non-goals

- **Auto-archival of stale entities.** The audit is observation-only.
  Auto-promoting `DEPRECATED → ARCHIVED` belongs in its own ADR; we
  want operator-visible findings first.
- **Dashboard widget.** Easy follow-up — `audit_ontology` is already
  consumable from the control plane via a thin Next.js reader. Out
  of scope for v4.21 to keep diff focused.
- **Time series.** Snapshot only. Trending `reanchor_events_in_window`
  over time is a worthwhile v4.2x sprint.
