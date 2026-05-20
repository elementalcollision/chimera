# ADR 0079 — Per-task budget cap (v4.60)

**Status:** Accepted (2026-05-20)

## Context

The cost-discipline arc has shipped three orthogonal caps:

| Cap | Scope | What it catches | When it trips |
|---|---|---|---|
| `CHIMERA_CYCLE_COST_CAP_USD` (v4.53) | One cycle | A single runaway cycle | mid-cycle |
| `CHIMERA_ROLLING_HOUR_CAP_USD` (v4.57) | Last 60 minutes across cycles | Slow burn | cumulative |
| **`CHIMERA_TASK_BUDGET_USD` (v4.60)** | **One INBOX task** across all its cycles | **A stuck task that keeps being re-promoted** | **per task** |

The 2026-05-19 burn pattern was the gap the per-task budget closes:
the dashboard-honesty-audit task burned through 5+ cycles, each one
blowing well past what would have been the per-cycle cap; the
rolling-hour cap would eventually trip but only after multiple
expensive cycles. Per-task accounting makes "this task is too
expensive — abandon it" an explicit, machine-enforced condition,
without needing to wait for the hour-window cap to accumulate.

The data was almost in place: `task_escalations` already stores
signatures, and signatures are deterministic from task text. The
missing link was: which `api_calls` rows belong to which task.

## Decision

### 1. Schema: link `api_calls` to a task signature

`chimera/memory/store.py` — additive migration:

```sql
ALTER TABLE api_calls ADD COLUMN task_signature TEXT;
CREATE INDEX IF NOT EXISTS idx_api_calls_task_signature
  ON api_calls(task_signature);
```

Pre-v4.60 rows have `NULL` task_signature — they're invisible to
the per-task budget computation (zero contribution), which is the
correct semantic.

### 2. ACT writes the signature on every `record_api_call`

`chimera/core/act.py` — at the top of `_execute_inner` compute
`task_sig = _signature(task_text)` once per task, and pass it to
every `record_api_call` in the round loop (both the success path
and the provider-error path).

The signature is the same token-bag form used by `task_escalations`
(`chimera.core.escalation._signature`), so the budget tally agrees
with the existing escalation-memory promotion logic.

### 3. Budget helpers in `chimera/core/budget.py`

```python
_DEFAULT_TASK_BUDGET_USD = 5.00

class TaskBudgetExceeded(Exception):
    def __init__(self, *, spend_usd, budget_usd, signature): ...

def task_budget_usd() -> float          # env CHIMERA_TASK_BUDGET_USD
def task_spend_usd(db, *, task_signature: str) -> float
def check_task_budget(db, *, task_signature: str) -> None
```

`task_spend_usd` is token-driven (same shape as `cycle_spend_usd`
and `rolling_spend_usd`): SUM(input_tokens, output_tokens) GROUP BY
model_id, then multiply by the current price table. Tier-price
changes apply retroactively when read.

### 4. ACT checks the budget alongside the other two caps

Same call site as ADR 0076's rolling-hour check, at the top of
each round before the provider call:

```python
try:
    check_cycle_cost_cap(self._db, cycle)
    check_rolling_hour_cost_cap(self._db)
    check_task_budget(self._db, task_signature=task_sig)
except CycleCostCapExceeded as exc:
    return ActResult(..., finish_reason="cost_cap", ...)
except RollingHourCostCapExceeded as exc:
    return ActResult(..., finish_reason="rolling_hour_cap", ...)
except TaskBudgetExceeded as exc:
    return ActResult(..., finish_reason="task_budget", ...)
```

`task_budget` joins `cost_cap` and `rolling_hour_cap` in the
escalation-memory exclusion list — a budget trip is a spend
problem, not a capability problem, so it does not promote the
tier on re-attempt.

### 5. Default: $5 per task

Default `CHIMERA_TASK_BUDGET_USD=5.00`. Rationale:

- Per-cycle cap is $2.00 (v4.53 default).
- A legitimate multi-cycle task that promotes haiku → sonnet
  (research-floor or memory-driven) typically completes in 2-3
  cycles. At ~$1–2 per healthy cycle, $5 fits.
- A task that's STUCK and keeps tripping the per-cycle cap will
  accumulate $2+/cycle until either rolling-hour or task-budget
  trips. $5 means it trips at cycle 3 — before the rolling-hour
  cap ($20) and well before any operator notices spend.

## Tests

`tests/test_task_budget.py` — 14 new tests:

- Env reader: default $5, override, zero disables, malformed falls back
- `task_spend_usd`: empty, attribution-by-signature (distinct sigs
  required), sums across cycles, ignores errored rows, defensive
  empty-signature case
- `check_task_budget`: no-op under budget, raises over budget,
  disabled when budget=0, no-op for empty signature
- Overnight-burn replay: one $10.5 cycle → next cycle's pre-flight
  check trips immediately (proving the cap catches the stuck-task
  pattern at the earliest possible boundary)

Full suite after v4.60: 641 passing (was 627, +14 new).

## Non-goals

- **Not auto-marking `[-]` in INBOX.** A budget trip exits the
  cycle with `finish_reason="task_budget"`; the inbox stays as-is
  so the operator decides whether to rewrite, split, or abandon
  the task. Auto-marking would be a write into operator-owned
  state without consent.
- **Not surfacing a "task spend" widget on the dashboard.** The
  per-task spend is computable via SQL against `api_calls`; if
  operators want a widget, that's a Tier 2 follow-up.
- **Not changing escalation-memory promotion rules.** A
  `task_budget` exit, like `cost_cap` and `rolling_hour_cap`, does
  not record a `task_escalations` row, so the next attempt at the
  same signature starts fresh from whatever the memory said
  before. That's correct: re-promoting tier doesn't make a
  too-expensive task affordable; it just burns the budget faster.
- **Not backfilling `task_signature` on old rows.** Old rows stay
  NULL and contribute zero to the budget. The intent is to
  protect *future* runs, not retroactively diagnose past ones.

## Why this shape

Why $5 and not $10? Because the symptom we observed was
~$10/cycle. The cap should trip the cycle *before* the second
$10 lands, not after. $5 means cycle 1 ($10) → cycle 2 check
trips immediately ($10 > $5). $10 would let cycle 2 land before
tripping at cycle 3 — twice as much waste.

Why a separate ENV var instead of deriving from the per-cycle cap?
Because the budget is a different concept: per-cycle is "no one
cycle can be this expensive"; per-task is "no one task is worth
this much across all attempts." Operators may legitimately want
high cycle cap (deep research is allowed to cost $5/cycle) with
tight task budget ($10 total / task). Decoupling them keeps both
tunable.

Why use signature instead of an explicit task_id? Because we
already have signatures, they're deterministic from task text,
and `task_escalations` is keyed by them. Adding a task_id would
mean threading an identifier from inbox-parse → ACT → record_api_call;
signature gives us the same grouping for free.

Why exclude `task_budget` from escalation memory? Because
promoting a stuck task's tier just makes the next attempt
burn faster. The memory's job is "this task needed sonnet, not
haiku"; the budget's job is "this task isn't worth attempting at
all anymore until the operator changes something." Mixing them
would erode both.
