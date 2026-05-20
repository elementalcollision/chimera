# ADR 0073 — Engine + cost observability tightening (v4.54)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0072](./0072-cost-runaway-guards.md) committed to three follow-up
guards before any further long-horizon runs would be safe: (1) the
ladder inversion + cycle cost cap shipped in v4.53; this ADR lands
the remaining two (cost-rate alarm widget, engines-default-off for
long-horizon) plus three concerns surfaced by the agent's own
overnight artifacts in `mind/overnight/`.

The overnight artifacts were honest:

- `escalation-postmortem.md` named two anti-patterns: multi-section
  tasks on haiku always max-out rounds; ambiguous "pick two" selection
  tasks waste rounds on discovery. Recommendation #4: *"if any
  signature hits ≥ 2 escalations, escalate that signature to a human
  with the full task text and this postmortem format."*
- `self-proposals.md` re-endorsed three already-queued mutations
  (#7 spin-guard, #8 reflection→planner wiring, #13 cold-start
  curiosity gate) — all from the discovery/reflection engines, all
  small and reversible.
- ADR 0072 §2 left "trips a cap → silent in-cycle exit" as the only
  signal; the operator still needs an interactive surface that
  shows *trajectory* before the cap actually trips.

This ADR ties all of that together into one cohesive release.

## Decision

### 1. Cost-rate alarm widget (B1 from ADR 0072 §3)

- `control-plane/lib/db.ts` — new `apiCallTokenRowsLastMinutes(n)`
  reader (NULL-error filter, time-bounded by `datetime('now', '-N minutes')`).
- `control-plane/lib/cost.ts` — new `computeCostRate(buckets, minutes)`
  and `classifyCostRate(usdPerMin)`. Bands:
  - `green` < $0.10/min (normal interactive)
  - `amber` $0.10–0.50/min (review)
  - `red`   > $0.50/min (investigate)
  - `off`   no calls / window=0
  Reference point: the 2026-05-19 burn averaged $1.70/min — solid red
  inside 15 minutes.
- `control-plane/components/widgets/CostAlarmWidget.tsx` — new SSR
  widget reading the rolling-15m `CostRate` and rendering band +
  top-contributor model.
- Widget tile registered at `(x=0, y=16, w=4, h=4)` in the `cost`
  group of `app/page.tsx`.
- `STORAGE_LAYOUT` + `STORAGE_PINS` bumped v13 → v14 per the AGENTS.md
  storage-version convention.

### 2. Engines default OFF for long-horizon runs (B2 from ADR 0072 §4)

- `docs/runbook.md` — long-horizon shell-loop pattern rewritten:

  ```bash
  SEQ=${SEQ:-8}
  if [ "$SEQ" -ge 8 ] && [ -z "${CHIMERA_ENGINES_ENABLED:-}" ]; then
    export CHIMERA_ENGINES_ENABLED=0
  fi
  export CHIMERA_CYCLE_COST_CAP_USD=${CHIMERA_CYCLE_COST_CAP_USD:-2.00}
  ```

  Explicit opt-in (`CHIMERA_ENGINES_ENABLED=1`) still works for the
  operator who wants exploratory tasks during long runs. Default is
  off precisely because the engines compound cost in long-horizon
  mode (engines surface tasks faster than ACT can verify them, and
  on the opus tier those tasks compound spend — see the 2026-05-19
  overnight where engines added two diagnostic tasks during the
  thrash and both got opus-pinned).

### 3. Hot-signature alarm in `chimera escalations summary` (A17)

- `chimera/core/escalation.py` — new `HotSignature` dataclass and
  `hot_signatures(conn, *, threshold=2)` helper. Returns signatures
  with ≥ N total failures, sorted by total_failures desc. Each row
  carries: signature, total_failures, tiers (deduped, sorted),
  first/last-seen cycle, last finish_reason, and a 120-char excerpt
  of the most recent task_text.
- `chimera/cli.py` — `chimera escalations summary` now appends a
  `⚠️ HOT SIGNATURES` section after the existing tier-counts table
  whenever any signature has ≥ 2 failures. Operators see the alarm
  *without* needing to run a separate command.

The threshold is intentionally low (2) because the escalation
postmortem identified ≥ 2 as the inflection point where "tier was
wrong" tips into "task text needs rewriting." Below 2, the
escalation memory itself is doing the right thing; at ≥ 2 the human
should look.

### 4. Approve three queued mutations (A1, A2, A3)

These were already in the mutation queue, surfaced and endorsed by
the agent itself in `mind/overnight/self-proposals.md`. Approving
them is purely operator consent — implementation already done by the
engine that proposed them.

- **#7** (`prompt_injection`, `chimera/core/loop.py`) — loop-spin
  guard at cycle 3+: when the same tool+similar-args repeats within
  2 cycles, inject *"You've called {tool} for the {n}th time.
  Refining or spinning? Reply SPIN to skip to synthesis."*
- **#8** (`wiring`, `chimera/proposals/generate.py`) — bridge
  Reflection→Planner: inject today's Morning Discovery and Midday
  Curiosity sections from CHRONICLE.md into `build_plan_prompt()`
  before the history block.
- **#13** (`config_change`, `chimera/engines/curiosity.py`) — gate
  Midday Curiosity on a substantive Morning Discovery; cold-start
  days emit a 1-line stub instead of spawning a wiki/projects/qNNN
  investigation.

## Tests

`tests/test_hot_signatures.py` — pins:
- Empty `task_escalations` → `hot_signatures()` returns `[]`
- One failure on a signature → not hot (threshold default 2)
- Two failures on the same signature → present, `total_failures=2`,
  `tiers` contains both tier names if they differed
- Multiple signatures sort by `total_failures` desc
- Custom `threshold` parameter works
- `excerpt` is truncated to 120 chars
- Schema-missing case (missing table) returns `[]` without raising

No Python tests for `cost.ts` band thresholds — the TypeScript
functions are small (one ternary cascade, one arithmetic helper)
and adding Vitest/Jest infrastructure for two function tests would
be larger than the functions themselves. The classifications are
manually verified against the documented thresholds; if/when a
broader TS test harness lands, classifyCostRate is the first
candidate to pin.

Full suite after v4.54: 593 passing (was 583 at v4.53, +10 new
hot-signature tests).

## Non-goals

- **Not making `cost_usd` a written column.** Same position as
  ADR 0072: the dashboard's client-side computation is the source of
  truth. Populating cost_usd is a separate ADR if historical pricing
  drift ever needs to be tracked.
- **Not auto-killing a run on red band.** The widget surfaces the
  signal; the operator decides whether to kill. ADR 0072 §2 cycle
  cost cap is the auto-kill. They are complementary — cap is
  reactive on a single cycle's spend; the alarm is observational on
  the trajectory.
- **Not extending the hot-signature alarm into the dashboard yet.**
  CLI surface lands here; a dashboard widget for hot signatures is a
  natural follow-up (would pair with the existing model-utilization
  widget) but not needed for the v4.54 cost-discipline release.
- **Not changing the threshold.** 2 is the postmortem heuristic; if
  operators find it noisy, it's tunable via the function parameter
  but not exposed as env until we have signal.

## Why this shape

Why the band thresholds 0.10 / 0.50 / 1.70 / not some other split?
The 2026-05-19 burn averaged $1.70/min on the stuck task. $0.50/min
is the geometric midpoint between green and the actual catastrophe;
$0.10/min is roughly the steady-state cost of a healthy opus-rung
cycle (now, with the v4.53 ladder inversion, mostly deepseek-pro
plus occasional opus). Operators who run sustained sonnet+opus
work for an extended session will see amber; that's the right
signal — review what's running, decide if it's worth the spend.

Why surface hot signatures in `summary` rather than a separate
verb? Because the postmortem's whole point was that hot signatures
are the ones the operator most needs to see. Hiding them behind a
flag operators have to remember to set defeats the purpose. The
existing summary already enumerates signatures-by-tier-counts;
adding the hot-signatures section at the bottom of the same view is
zero extra cognitive load and high information value.

Why approve three mutations instead of just listing them as
"recommended"? Because the agent (a) generated them, (b) endorsed
them in `self-proposals.md` with explicit re-recommendation, and
(c) each is a small, reversible config change with named files and
clear briefs. Operator review consists of reading the briefs, which
the agent already wrote. The 2026-05-19 self-proposal artifact is
the review document.
