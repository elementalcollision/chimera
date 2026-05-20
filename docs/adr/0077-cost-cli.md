# ADR 0077 — `chimera cost` CLI verb (v4.58)

**Status:** Accepted (2026-05-20)

## Context

ADR 0073 added the cost-rate alarm widget on the dashboard;
ADR 0076 added the rolling-hour cap. Both rely on the operator
running the dashboard. For headless / SSH / container-only use,
there is no operator-facing surface for cost — only the per-cycle
hard cap (silent until tripped) and the api_calls table (raw).

The 2026-05-19 burn was the canonical example: even with the
dashboard available, the operator did not notice the trajectory
for two hours. A CLI surface lets the operator query spend at any
moment without spinning up the Next.js dashboard, and gives a
machine-readable JSON path for shell-loop guards.

## Decision

### `chimera cost` verb

`chimera/cli.py` — new subparser:

```
chimera cost [--json] [--cycle N]
```

Output (text mode):

```
chimera cost  band=off  ($/min over 15m: $0.000)
  cycle  38 spend  $  11.93  (cap $2.00)
  15m rolling    $   0.00
  60m rolling    $   0.00  (cap $20.00)
  total          $ 231.77

  by model (descending):
    claude-opus-4-7                      $ 229.35
    deepseek-v4-pro                      $   1.39
    deepseek-v4-flash                    $   1.04

  ⚠️  cycle spend OVER per-cycle cap ($2.00)
```

JSON mode emits the same fields as a structured payload:
`{cycle, cycle_spend_usd, cycle_cap_usd, spend_15m_usd,
spend_60m_usd, rolling_hour_cap_usd, usd_per_min_15m, band,
total_usd, by_model: [{model_id, cost_usd}, …]}`.

The verb is **read-only** — no schema migrations, no writes. It
reuses the v4.53/v4.57 budget helpers (`cycle_spend_usd`,
`rolling_spend_usd`, `cycle_cost_cap_usd`, `rolling_hour_cap_usd`,
`_price_table`) so the CLI report and the dashboard widgets agree
by construction.

### Band classification

Mirrors the dashboard's `classifyCostRate()` in `lib/cost.ts`:
- `off` → no calls / window=0
- `green` → < $0.10/min
- `amber` → $0.10–0.50/min
- `red` → > $0.50/min

Text mode also flags over-cap conditions with ⚠️ markers for cycle
and rolling-hour caps separately.

### `--cycle N` flag

Default reports on `MAX(cycle)` from `api_calls`. Explicit
`--cycle N` lets the operator drill into a specific historical
cycle (e.g. to confirm an old burn's per-cycle spend matches the
cap at the time).

## Tests

`tests/test_cost_cli.py` — 4 subprocess-driven tests:

- Empty DB → JSON has `total_usd=0`, `band="off"`, `by_model=[]`,
  caps honored from env
- DB with $15 opus row → JSON reports cycle/total/by_model
  correctly; text mode shows `OVER per-cycle cap` warning
- Explicit `--cycle N` selects the right cycle's spend (vs. default
  which picks `MAX(cycle)`)
- All four exit 0 (the verb is read-only; failure modes are
  hardened against missing schema via `try/except` around the
  total-spend SELECT)

Full suite after v4.58: 619 passing (was 615, +4 new).

## Non-goals

- **No write surface.** This is observation only. Any cost cap or
  hot-signature mutation goes through existing `chimera mutations
  approve` / env overrides.
- **No watch mode.** A `--watch` flag that loops + refreshes would
  duplicate `watch chimera cost --json | jq …` shell pipelines.
  Operators who want streaming have it via standard tools.
- **No projection past current spend.** That's [ADR 0078] — the
  pre-flight cost estimation verb — a separate CLI verb / mode.
- **No per-task breakdown.** That belongs with [ADR 0079] — the
  per-task budget cap — because the data model (task signature →
  cost contribution) is what that ADR introduces.

## Why this shape

Why a separate `chimera cost` verb and not `chimera doctor cost`?
Because `chimera doctor` is a preflight / config validator —
"does this environment work?" — and cost is a runtime state
query. Conflating them would confuse the doctor surface. Keeping
them separate also lets `chimera cost --json` pipe cleanly into
shell-loop guards (e.g.,
`band=$(chimera cost --json | jq -r .band); [ "$band" = "red" ] && exit`).

Why include `by_model` in the verb when the dashboard widget
already shows it? Because for headless operators that's their
only view, and because the JSON output is the contract for
external monitoring scripts. Dashboard ≠ source of truth; the DB
is. The CLI is the lightweight read-path against that source.
