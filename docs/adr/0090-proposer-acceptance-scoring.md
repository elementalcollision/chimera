# ADR 0090 — Proposer acceptance-rate scoring → demotion (v4.71)

**Status:** Accepted (2026-05-20)

## Context

`mind/postmortems/engine-telemetry-2026-05-20.md` §1 catalogued the
acceptance ratios across the four months of mutation history:

> ```
> skill_proposal     applied=1  rejected=2  failed=2  pending=3
> config_change      applied=3  rejected=2  failed=0  pending=0
> task_split         applied=2  rejected=1  failed=0  pending=4
> ```
>
> `skill_proposal` is the worst offender: 4 noise rows for every applied
> row, with the operator quietly leaving the rest pending because they're
> not worth the friction of an explicit reject.

The same section named the proposal:

> **P3 — Engine acceptance-rate scoring → demotion.** Track per-engine
> `proposal_acceptance_rate = (approved+applied) / (approved+applied+rejected)`
> over the last N proposals (default 10). When the rate falls below
> 50%, the engine gets a `degraded` flag. Degraded engines still fire
> and still write to chronicle, but do NOT propose new mutations.
> Operator can promote back by `chimera engines promote curiosity`.

This ADR ships P3 with two refinements that fell out during build:

1. **"Engine" → "proposer."** The observation engines
   (Discovery/Curiosity/Reflection) don't directly emit mutations.
   The proposers are the *mutation types* (`skill_proposal`,
   `task_split`, `config_change`, …). Scoring those is exact;
   scoring engines would require either coupling each engine to a
   proposer (it doesn't exist today) or attributing creator at
   `create_mutation` time (a separate refactor). Per-type scoring
   captures the operator's actual signal directly.
2. **Counting policy.** `applied` is accepted; `rejected` and
   `failed` are both rejected (an applied-but-broken mutation is
   noise from the operator's view). `pending` and `expired` are
   excluded — they don't represent a decision.

## Decision

### New module `chimera/core/proposer_scoring.py`

Pure functions over the `mutations` table plus a small persistence
table:

| Function | Purpose |
|---|---|
| `compute_score(db, proposer)` → `ProposerScore` | rolling window count |
| `evaluate_and_update(db, proposer)` | recompute + auto-flag degraded |
| `check_can_propose(db, proposer)` → `(allow, reason)` | gate for `create_mutation` |
| `promote(db, proposer)` | operator: clear degrade |
| `pause(db, proposer)` | operator: sticky pause |
| `all_scores(db)` | dashboard / CLI list |

`ProposerScore(accepted, rejected, decided, rate, window)` —
`rate=None` when no decisions yet (refuses to demote on insufficient
data; conservative default).

### New table `proposer_status`

```sql
CREATE TABLE proposer_status (
    proposer        TEXT PRIMARY KEY,         -- mutation.type
    status          TEXT NOT NULL,            -- 'active' | 'degraded' | 'paused'
    reason          TEXT,
    last_rate       REAL,
    last_decided    INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);
```

Single row per proposer-type. `active` is the implicit default
(absence of row = active). `degraded` is auto-assigned by the
scoring loop. `paused` is operator-set and **sticky** — re-eval
won't clear it; only an explicit `promote` does.

### Hook into `create_mutation`

```python
allow, deny_reason = check_can_propose(conn, type)
if not allow:
    raise ProposerDegradedError(type, deny_reason)
```

A degraded proposer's next attempt to enqueue raises rather than
silently dropping. Callers in `chimera/core/adaptation.py`,
`chimera/core/task_split_proposal.py`, and `chimera/memory/audit.py`
already wrap their proposer work in try/except for queue health;
the new exception flows through.

### Hook into terminal transitions

`mark_applied`, `mark_failed`, and `reject_mutation` call
`_reeval_proposer(conn, m)` after the write. This recomputes the
rolling score and upserts `proposer_status` — so the next
`create_mutation` sees the up-to-date gate state without any
housekeeping cron. Best-effort: any exception in re-eval is swallowed
so the underlying write never fails on a scoring bug.

### CLI: `chimera proposers`

```
chimera proposers list                    # acceptance + status per type
chimera proposers promote skill_proposal  # clear degrade
chimera proposers pause skill_proposal    # sticky pause
```

`list` output:

```
chimera proposers: 3 type(s)
  skill_proposal           degraded rate=  20% (1/5 in last 10)
    └─ acceptance 1/5 = 20% < 50% over window=10
  task_split               active   rate=  67% (2/3 in last 10)
  config_change            active   rate=  60% (3/5 in last 10)
```

`--json` emitter for the dashboard.

### Configuration knobs

| Env | Default | Purpose |
|---|---|---|
| `CHIMERA_PROPOSER_SCORING_ENABLED` | `1` | master switch |
| `CHIMERA_PROPOSER_SCORE_WINDOW` | `10` | rolling window size |
| `CHIMERA_PROPOSER_SCORE_THRESHOLD` | `0.5` | global threshold |
| `CHIMERA_PROPOSER_<TYPE>_THRESHOLD` | inherits | per-type override |

Master off → `check_can_propose` always allows; `evaluate_and_update`
is a no-op. Useful for scripted scenarios that want to exercise
proposers without queue-health interference.

## Tests

`tests/test_proposer_scoring.py` — 19 new tests:

- Master switch (default on / off)
- `compute_score`: empty, mixed applied+rejected+failed, ignores
  pending+expired, window override
- `evaluate_and_update`: demotes on low rate, leaves active alone
  when healthy, recovers from degraded on operator-promoted retry
- `paused` is sticky (100% rate still leaves it paused)
- `create_mutation` raises `ProposerDegradedError` when degraded;
  works again after `promote`
- `pause` blocks `create_mutation`
- Master-off bypasses paused (sanity check)
- Per-proposer env threshold override
- `all_scores` lists every seen type
- Re-eval auto-fires on `reject_mutation`

Plus an autouse fixture in `tests/test_engines.py` that disables
the v4.70 gates (so legacy engine tests don't need to seed
api_calls / chronicle).

Full suite after v4.71: 770 passing (was 767, +19 new minus 0 lost).

## Non-goals

- **No automatic demotion of observation engines.** Discovery /
  Curiosity / Reflection don't propose mutations; they write to
  chronicle. Scoring them by mutation acceptance would be a
  category error. A future ADR can add chronicle-quality scoring
  if a meaningful signal exists.
- **No `approved`-state counting.** The post-mortem's formula
  included `approved` in the numerator, but `approved` is a
  transient state in our queue (the runner moves it to `applied`
  or `failed`). Counting it would double-count successful
  applications. We use the terminal states only.
- **No automatic promote.** Recovery via `evaluate_and_update`
  clears a `degraded` row when the rolling rate climbs back ≥
  threshold — but only if the proposer was making decisions, which
  requires promote-then-propose. So in practice the operator has to
  take the first step (rewrite the prompt, then promote).
- **No demote-history table.** A row's status overwrites on each
  re-eval; we don't keep an audit trail. The dashboard can
  reconstruct from `mutations` if needed. Adding a journal is
  cheap if/when the operator wants it.

## Why this shape

Why mutation.type as the key, not a new "proposer" column? Because
type already segregates by code path that produced the row, and
adding a column means a migration, a backfill, and updating every
`create_mutation` site to pass it. The type column does the work.

Why does `check_can_propose` raise instead of return False? Because
the operator wants the proposer to **stop** when degraded, not to
silently drop. Raising surfaces it in the cycle's error log and in
`engine_runs.status="failed"` — visible signal that the gate is
working. Callers that want the soft-fail behaviour can catch the
exception.

Why paused-is-sticky? Because the operator's intent is "I don't want
this proposing while I redesign it." Auto-promoting on the next
healthy decision (which can't happen with create_mutation blocked
anyway) would erase that intent on the operator's behalf.

Why no dashboard widget in this ADR? Because the CLI is the
primary surface today; the dashboard read-only mirror is a follow-up
when we surface this as a card next to the queue-health widget. The
JSON output of `chimera proposers list --json` is the API the
dashboard will consume.
