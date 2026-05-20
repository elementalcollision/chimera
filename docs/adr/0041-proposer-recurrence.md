# ADR 0041 — Auto-proposer recurrence + queue health (v4.19)

**Status:** Accepted (2026-05-19)

## Context

The mutation queue is "Chimera proposes, the operator disposes." But
proposing the same thing twice — or sixteen times — is operator noise.
v4.5 already prevented duplicate enqueues via `_already_proposed`
(Jaccard ≥ 0.5 on the signature_tokens payload), but the suppression
was silent. We had no way to tell whether a fragmentation pattern hit
once and got fixed, or kept recurring and the operator was missing it.

There was also no queue-health surface at all: nobody could answer
"how many pending? oldest age? approval ratio?" without raw SQL.

## Decision

Two additive changes:

### 1. Recurrence counter

- New column `mutations.recurrence_count` (NOT NULL DEFAULT 0). Added
  via idempotent `ALTER TABLE … ADD COLUMN` in `init_schema`; no
  PRAGMA bump (additive column per [ADR 0025](./0025-v4-stability.md)).
- `_already_proposed` now returns `int | None` (the matching pending
  row's id) instead of `bool`. Restricted to `status='pending'` so a
  once-rejected proposal can be re-emitted if the failure keeps
  recurring.
- `maybe_propose_synthesis_skill` on a duplicate calls
  `bump_recurrence(conn, mid)` and returns the existing id. Operators
  see "this fragmentation hit 8 times" via a single row instead of
  eight separate rows.

### 2. `queue_health(conn)`

Returns a single dict:

```python
{
  "counts": {"pending": 2, "applied": 1, "rejected": 1},
  "pending_oldest_age_seconds": 312,
  "pending_recurrence_max": 5,
  "pending_recurrence_total": 9,
  "approved_ratio": 0.5,  # applied / (applied + approved + rejected + failed)
}
```

Exposed via `chimera mutations health [--json]`. Operators (and the
control plane, when wired) can now see at a glance whether the queue
is healthy or accumulating noise.

## Behavior change

- **Caller contract**: `maybe_propose_synthesis_skill` no longer
  returns `None` on a duplicate. It returns the existing id, same as
  it returns the new id on a fresh enqueue. `None` now strictly means
  "fragmentation threshold not met yet."
- Existing test in `tests/test_adaptive_budget.py` updated to assert
  `second == first` and `recurrence_count == 1`.

## Tests

- `tests/test_mutations.py` — five new tests:
  - `test_bump_recurrence_increments_in_place`
  - `test_bump_recurrence_missing_id_returns_none`
  - `test_queue_health_empty`
  - `test_queue_health_mixed`
  - `test_adaptation_already_proposed_bumps_existing`
- Full suite: 508 passing, 5 skipped (was 503 / 5).

## Non-goals

- **Dashboard widget**: not in v4.19. The CLI verb is enough to use
  the metric today; the canvas widget is a small follow-up.
- **Per-type recurrence dedup**: only `skill_proposal` mutations get
  the signature-token dedup today (it's the only path that emits
  signature tokens). Other mutation types are still 1:1 with their
  emitter.
- **Schema-version bump**: not required — the column is nullable with
  a default per [ADR 0025](./0025-v4-stability.md).
