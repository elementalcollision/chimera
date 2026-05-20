# ADR 0083 — Audit `dead_entity` query uses transitions, not activity log (v4.64)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0074](./0074-audit-and-kfm-safety.md) §"Finding 3" documented a
latent bug the overnight code review surfaced and which the
operator's `grep` verification confirmed:

> `cell_ref` is NEVER set in production. `chimera/core/loop.py:749`
> is the only production caller of `record_activity()` and it
> omits `cell_ref` entirely. The audit dead-entity query joins on
> `WHERE a.cell_ref = e.id`, so it matches zero rows in production
> — meaning every non-terminal entity reports as "dead." The test
> fixture in `test_audit_ontology.py` explicitly passes
> `cell_ref=e.id`, exercising a path production doesn't.

The fix was deferred from ADR 0074 because the right design wasn't
obvious between two options:

  **A.** Backfill `cell_ref` everywhere production calls
  `record_activity` — but those calls are *phase-scoped*
  (HOUSEKEEPING, WAKE, …), not entity-scoped. There's no entity to
  attribute to.

  **B.** Redefine the "dead" signal against a table that actually
  has entity-scoped rows — `entity_transitions`. Every state move
  writes a row with `entity_id` and `cycle`.

Option B wins on honesty: it uses the data we actually have. The
trade-off is documented below.

## Decision

`chimera/memory/audit.py:_audit_ontology_inner` — `dead_rows` query
changes from:

```sql
NOT EXISTS (
    SELECT 1 FROM agent_activity_log AS a
    WHERE a.cell_ref = e.id          -- always NULL in prod
      AND a.cycle > ?
)
```

to:

```sql
NOT EXISTS (
    SELECT 1 FROM entity_transitions AS t
    WHERE t.entity_id = e.id          -- always populated
      AND t.cycle > ?
)
```

Same scoping (excludes `ARCHIVED` and `KILLED`); same window
parameter; same caller surface. No schema change, no migration —
the `entity_transitions` table has existed since v2.0 and is the
canonical lifecycle log.

### Semantic change

Pre-v4.64 (broken): every non-terminal entity reports as dead.
Useless signal.

Post-v4.64 (honest): an entity is "dead" iff its `kfm_state` is
non-terminal AND `entity_transitions` has no row with a `cycle`
inside the audit window.

### Known limit

An entity that has been STABLE for many cycles and is actively used
by the agent but has never been transitioned (no demotion, no
re-anchor) will still report as "dead." That's because the only
entity-scoped signal we have is the lifecycle table.

This is a *stricter* definition than the original v4.21 intent
("untouched in N cycles") but it's the most honest one given the
data we collect. A future ADR can extend the signal — e.g. write
an `agent_activity_log` row with `cell_ref=entity_id` from
`transition_entity`, OR introduce a dedicated `entity_touched_at`
column. Either is its own design decision; this ADR limits scope
to "stop reporting every non-terminal entity as dead."

## Tests

`tests/test_audit_ontology.py` — 3 new regression tests:

- `test_dead_excludes_recently_transitioned_entity` — entity with a
  transition inside the window is NOT in dead_entities
- `test_dead_flags_entity_with_only_old_transitions` — entity whose
  transitions all predate the window IS dead
- `test_dead_does_not_misreport_under_old_cell_ref_bug` — entity
  with current-cycle transitions is NOT dead (the original bug
  always reported it as dead)

Existing dead/stale/terminal-state tests continue to pass.

Full suite after v4.64: 686 passing (was 683, +3 new).

## Non-goals

- **Not backfilling `cell_ref` in production.** Loop activity rows
  are phase-scoped; there's no single entity to attribute to. The
  field stays nullable; no caller is asked to populate it.
- **Not introducing a new "touched_at" signal.** That's its own
  design decision (probably needs a dedicated column on `entities`
  plus a hook into every place an entity is touched). Scoped out.
- **Not changing the stale-entity query.** The `state_entered_at_cycle`
  signal it uses is correct and unaffected by this fix.

## Why this shape

Why the transition table and not `state_entered_at_cycle`?
Because `state_entered_at_cycle` is rewritten every time the entity
transitions, so "WHERE e.state_entered_at_cycle <= cutoff" gives
the same answer as "WHERE no transitions in window" for the
current state — but the SQL is less explicit about what we're
asking. The join against `entity_transitions` makes the semantic
visible: "no lifecycle event in the window."

Why not also write to `agent_activity_log` from `transition_entity`?
Because that would conflate two purposes — the activity log is for
loop-phase events; the transitions table is for lifecycle events.
Forcing one to populate the other creates double-writes and
duplicates the audit signal across two tables. The cleaner
architecture is "use the right table"; that's what this fix does.

Why now and not as a follow-up to v4.74 (e.g. via the engine
post-mortem)? Because every dashboard / CLI surface that displays
the dead count has been lying since v4.21. That's 60+ versions of
operator-visible misinformation. Fixing it costs one SQL edit and
three tests.
