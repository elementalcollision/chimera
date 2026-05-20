# ADR 0046 — Auto-archive stale DEPRECATED entities (v4.24)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0043](./0043-ontology-audit.md) (v4.21) added a memory audit that surfaced
`deprecated_unarchived` — entities that the K-operator demoted from
STABLE but that never moved on to ARCHIVED. The DEPRECATED → ARCHIVED
transition existed in the linear KFM lifecycle but no code path
actually drove it. Result: deprecated entities accumulate forever,
inflating the ontology and the graph projection.

## Decision

A loop-integrated auto-archival policy.

### `auto_archive_stale_deprecated(conn, *, current_cycle, archive_after_cycles=30, max_per_cycle=25, dry_run=False)`

Lives in `chimera/memory/audit.py` alongside `audit_ontology` —
"audit then act," same threshold semantics.

Behavior:

- Selects all entities currently in `kfm_state='DEPRECATED'` whose
  `state_entered_at_cycle` is at least `archive_after_cycles` behind
  `current_cycle`.
- For each, calls `transition_entity(..., to_state='ARCHIVED',
  operator_type='k')`. K-operator is the only operator authorised for
  this transition (per [ADR 0003](./0003-reggio-loop.md) / KFM lifecycle).
- Capped at `max_per_cycle` so a backlog never monopolises one
  housekeeping pass.
- `dry_run=True` returns the would-archive list without writing.
- Failures are logged and skipped — one bad entity doesn't stall the
  sweep.

### Loop integration

`_phase_housekeeping` (previously an MVP stub) now calls
`auto_archive_stale_deprecated` every cycle. Controlled by:

| Env var | Default | Meaning |
|---|---|---|
| `CHIMERA_AUTO_ARCHIVE_DISABLED` | unset | Set to 1/true/yes to skip |
| `CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES` | 30 | Threshold |

The housekeeping phase activity record now includes
`archived_count` so the dashboard can trend it.

### CLI

```
chimera ontology --archive-stale [--archive-after-cycles 30] [--dry-run]
```

Mirrors the audit verb. Useful for operator-triggered cleanups
without waiting for the loop.

## Tests

`tests/test_audit_ontology.py` — 5 new tests:

- `test_auto_archive_promotes_stale_deprecated` — happy path, asserts
  `kfm_state == ARCHIVED` and `state_entered_at_cycle` updated
- `test_auto_archive_skips_recent_deprecated` — under threshold → no-op
- `test_auto_archive_dry_run_does_not_transition` — preview semantics
- `test_auto_archive_max_per_cycle_caps_work` — batch cap honoured;
  remainder waits for next cycle
- `test_auto_archive_ignores_non_deprecated` — STABLE entity untouched

Full suite: 522 passing, 5 skipped (was 517 / 5, +5 new).

## Non-goals

- **Skipping ARCHIVED → KILLED.** That's an intentionally manual
  operator action — ARCHIVED preserves history, KILLED wipes it.
  Not part of this policy.
- **Per-kind thresholds.** All kinds use the same
  `archive_after_cycles`. A future ADR can split that if plans need
  a different rate than tools or skills.
- **Restoring archived entities.** Out of scope; the KFM lifecycle
  is linear today.
