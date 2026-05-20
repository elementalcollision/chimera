# ADR 0076 — Rolling-hour cost cap + cost_usd population (v4.57)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0072](./0072-cost-runaway-guards.md) shipped the per-cycle cost
cap and called out two unfixed concerns:

1. **`api_calls.cost_usd` is never populated.** The column exists,
   but ACT never passes a value when recording an API call. The
   dashboard widgets compute cost client-side from `input_tokens ×
   tier_price`, which works — but the DB column being empty means
   `chimera doctor`, SQL-driven cost queries, and any future
   alarms can't see real spend without recomputing.

2. **The per-cycle cap is a short-window control.** It catches one
   runaway cycle but not a sequence of cycles each staying just
   under the cap. The 2026-05-19 burn averaged $1.70/min × 135min;
   even with `CHIMERA_CYCLE_COST_CAP_USD=2.00`, a sequence of 10
   bad cycles back-to-back at $1.99 each would accumulate $20
   before the operator noticed. Long-window protection is needed.

A third bug surfaced while implementing the rolling-hour cap that
would have silently corrupted any windowed cost query:

3. **Timestamp format mismatch.** `record_api_call` writes ISO
   timestamps with T-separator and `+00:00` timezone
   (`2026-05-20T01:34:56+00:00`); SQLite's
   `datetime('now', '-N minutes')` returns space-separated, no-tz
   (`2026-05-20 00:34:56`). Raw string comparison
   (`created_at >= datetime('now', '-60 minutes')`) puts `T` (84)
   higher than space (32) at position 10, so **rows older than the
   window evaluated as "within" the window**. The rolling-window
   readers and any future cost-bounded query would have silently
   overcounted spend.

## Decision

### 1. Populate `cost_usd` at write time

`chimera/core/act.py` — when recording an `api_calls` row after a
successful provider response, compute `cost_usd` from the
in-process `_price_table` (already maintained by
`chimera/core/budget.py` and sourced from
`chimera/providers/tiers.py`) and pass it through:

```python
from .budget import _price_table as _bp_price_table
_prices = _bp_price_table()
_in_price, _out_price = _prices.get(response.model_id, (0.0, 0.0))
_in_tok = response.input_tokens or 0
_out_tok = response.output_tokens or 0
cost_usd = (_in_tok / 1_000_000.0) * _in_price + \
           (_out_tok / 1_000_000.0) * _out_price
record_api_call(..., cost_usd=cost_usd if cost_usd > 0 else None, ...)
```

Existing NULL rows stay NULL — no migration required. The cycle-spend
and rolling-spend computations continue to recompute from tokens
(so a tier-price update applies retroactively when read), but
downstream SQL queries that prefer the stored value can now
`SUM(cost_usd) FILTER (WHERE cost_usd IS NOT NULL)` for v4.57+
data.

### 2. Rolling-hour spend cap

`chimera/core/budget.py`:

- New constant `_DEFAULT_ROLLING_HOUR_CAP_USD = 20.00`
- New exception `RollingHourCostCapExceeded(spend_usd, cap_usd, window_minutes=60)`
- New env reader `rolling_hour_cap_usd()` honoring
  `CHIMERA_ROLLING_HOUR_CAP_USD`
- New `rolling_spend_usd(db, *, minutes=60)` — token-driven recompute
- New `check_rolling_hour_cost_cap(db)` — raises if 60m spend ≥ cap

`chimera/core/act.py` — round loop calls both checks at the top of
each iteration, before the provider call:

```python
try:
    check_cycle_cost_cap(self._db, cycle)
    check_rolling_hour_cost_cap(self._db)
except CycleCostCapExceeded as exc:
    return ActResult(..., finish_reason="cost_cap", ...)
except RollingHourCostCapExceeded as exc:
    return ActResult(..., finish_reason="rolling_hour_cap", ...)
```

Both finish reasons are excluded from `record_failure` so neither
trips the escalation memory's tier promotion (same reasoning as
v4.53 — a cap trip is a spend problem, not a capability problem).

Default $20/hour = roughly 10× the per-cycle cap, matching the
operational "if I see red on the alarm widget for an hour, this
run is broken" intuition.

### 3. Timestamp normalization

Both `chimera/core/budget.py:rolling_spend_usd` and the dashboard
reader `control-plane/lib/db.ts:apiCallTokenRowsLastMinutes` now
wrap `created_at` in `datetime(...)` so SQLite parses the ISO
string before comparison:

```sql
-- before (silently buggy)
WHERE created_at >= datetime('now', '-N minutes')
-- after
WHERE datetime(created_at) >= datetime('now', '-N minutes')
```

This is a strict bug fix; the v4.53 per-cycle cap is unaffected
because it filters on `cycle = ?` not on `created_at`.

## Tests

`tests/test_rolling_hour_cap.py` — 11 new tests:

- Default cap is $20.00
- Env override honored
- Zero disables enforcement
- Malformed env falls back to default
- Empty DB → spend = 0
- 2-hour-backdated row excluded from 60m window (the timestamp
  normalization regression check)
- Errored calls excluded
- No-op under cap
- Raises over cap with correct cycle / cap / window fields
- Disabled when env=0
- Overnight-burn replay: 60min of opus spend trips at first
  check, well over $20
- `record_api_call` persists `cost_usd` when supplied

`tests/test_cycle_cost_cap.py` — pre-existing tests still pass;
`record_api_call` taking `cost_usd` was already supported.

Full suite after v4.57: 615 passing (was 605 at v4.56, +10 new
hour-cap tests + 1 cost_usd persistence). The 2-hour-backdated
test catches the timestamp normalization bug as a regression.

## Non-goals

- **Not adding `cost_usd` to the per-cycle cap recompute.** The
  cycle-spend computation still recomputes from tokens because
  tier-price updates should apply retroactively when read. The
  column being populated is for downstream consumers (a future
  `chimera doctor cost` verb, e.g.) that want a stored point-in-time
  value without redoing arithmetic.
- **Not changing the timestamp write format.** Production writes
  ISO with T-separator and tz; that's correct for general
  interop. The fix is on the read side (wrap in `datetime()`).
- **Not exposing `--minutes` as a tunable on the rolling cap.**
  60 minutes is the unit; if a future operator wants a 30-min or
  3-hour cap, that's a follow-up ADR. The default + env knob is
  enough for now.
- **Not surfacing rolling-hour trip count on the dashboard.** The
  existing cost-rate alarm widget (ADR 0073) already shows the
  trajectory; the cap acts as the hard stop. A trip-history widget
  is a natural follow-up but not in this ADR.

## Why this shape

Why $20/hour as the default and not $5 or $50? Because $20/hour =
$2/cycle × 10 cycles ≈ 2 hours of normal sustained work at the
short-window cap. Lower and we false-trip on legitimate long
research sessions; higher and the 2026-05-19 burn ($229 in 2.25
hours) wouldn't have tripped soon enough. $20 is the
operationally-honest answer: it gives operators a 1-hour grace
window for normal work and trips well before the day's spend
becomes painful.

Why distinct exception types for cycle vs rolling? Because the two
have different remediation. Cycle cost_cap → "this task is wrong
on this tier; cap reset on cycle boundary; try again." Rolling cap
→ "the day has been expensive; the operator should review trends
before any further work." Telling them apart in the log and in
metadata is operationally useful.

Why fix the timestamp bug as part of this ADR and not a separate
one? Because the rolling cap can't be tested without fixing it
(the test was failing exactly because of the bug). Splitting would
mean shipping a broken-by-test rolling cap or skipping the test;
neither is acceptable. The fix is one line in two files and is
self-contained.
