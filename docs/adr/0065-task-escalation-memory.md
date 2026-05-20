# ADR 0065 — Persistent task-escalation memory (v4.46)

**Status:** Accepted (2026-05-19)

## Context

The Agonistic Futures cycle 14 burned 26 rounds on
`deepseek-v4-flash` (the cheapest rung) and never escalated. The
agent had no memory that the SAME task had hit `max_rounds` on a
prior cycle — so it cheerfully retried at the bottom of the ladder.

`chimera/core/escalation.py` already implements *within-cycle*
escalation for write-intent misses (PR #58), but there is no
*cross-cycle* memory. v4.46 fills that gap.

## Decision

A new SQLite table `task_escalations` records every non-completion
ACT exit:

```sql
CREATE TABLE task_escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signature       TEXT NOT NULL,    -- sorted-token frozenset
    task_text       TEXT NOT NULL,
    tier            TEXT NOT NULL,    -- tier used on the failed attempt
    finish_reason   TEXT NOT NULL,    -- max_rounds | artifact_missing | degenerate_loop_abort
    rounds_used     INTEGER NOT NULL,
    cycle           INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_task_escalations_signature ON task_escalations(signature);
```

Two helpers in `chimera/core/escalation.py`:

- `record_failure(conn, *, task_text, tier, finish_reason, rounds_used, cycle)` — appends a row if `finish_reason ∈ ESCALATING_FINISH_REASONS`. `stop` (success) and `provider_error` (upstream/transient) are intentionally excluded.
- `recommended_tier(conn, *, task_text, default_tier) -> str` — Jaccard-matches the incoming task signature (overlap ≥ 0.5) against history and returns one rung above the worst prior failure. Capped at `opus`; never below `default_tier`.

### ACT integration

`ActExecutor.execute` is now a thin wrapper that:

1. Calls `recommended_tier(self._db, task_text=task_text, default_tier=self._tier)` and promotes `self._tier` if needed (logged via `logger.info`).
2. Delegates the actual cycle to `_execute_inner` (the old execute body, unchanged).
3. On exit, if `result.completed is False`, calls `record_failure` so the next cycle has the data.

All four `ActResult` exit paths (max_rounds, provider_error, artifact_missing, degenerate_loop_abort) reach this single recording point.

### Failure-reason policy

| Reason | Records? | Why |
|---|---|---|
| `stop` | No | Success — nothing to memorise. |
| `max_rounds` | Yes | Tier was insufficient or task was too hard. |
| `artifact_missing` | Yes | Model claimed done but couldn't deliver — same diagnosis. |
| `degenerate_loop_abort` | Yes | Tool guard fired; symptom of model thrashing on the wrong tier. |
| `provider_error` | No | Upstream / transient — tier choice isn't the cause. |
| `provider_unavailable` | No | Config issue, not learning data. |

## Tests

`tests/test_task_escalation.py` — 11 tests:

- Signature is case/order/punctuation-insensitive, drops <4-char tokens.
- `record_failure` only memorises escalation-worthy reasons.
- `recommended_tier` returns default with no history.
- Promotes haiku→sonnet, sonnet→opus, and caps at opus.
- Doesn't promote across unrelated signatures.
- ACT executor end-to-end:
  - `test_act_executor_records_failure_on_max_rounds` — exhausting rounds writes a row.
  - `test_act_executor_promotes_tier_on_repeat_task` — a pre-seeded haiku failure promotes the next attempt to sonnet.

Full suite: **557 passing**, 5 skipped (+11 new).

## Non-goals

- **Dashboard widget.** A small "escalations by signature" view would be useful; not in v4.46 to keep diff focused.
- **Decay.** Old escalations stay forever. If a task that failed at haiku 6 months ago WOULD now succeed at haiku (better prompts, better model), we'd still promote it. A v4.5x sprint can add a TTL or recency filter.
- **Operator override.** No CLI to clear / inspect escalations yet. `chimera ontology --audit` could be extended, or a new `chimera escalations` verb.
