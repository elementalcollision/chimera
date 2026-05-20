# ADR 0078 — Pre-flight cost estimation (v4.59)

**Status:** Accepted (2026-05-20)

## Context

The cost-discipline arc (ADRs 0072–0077) shipped reactive controls:
caps that trip when spend has already happened, a widget that
shows current spend, a CLI that reports it. None of them answer
the question the operator asks **before** kicking off a long-horizon
run: *"how much will this cost?"*

The 2026-05-19 burn would have been preventable in two ways:
- **Reactive** (now shipped): per-cycle cap, rolling-hour cap, alarm
  widget, CLI report.
- **Prospective** (not yet shipped): estimate the cost from the
  INBOX state and the escalation memory before committing.

The operator's mental model is: open the inbox → see N tasks →
decide whether to run. A `chimera estimate` verb that says *"these
N tasks will cost about $X over roughly Y cycles"* closes the
prospective loop. It can also flag tasks whose per-cycle projection
already exceeds the cycle cap — those will hit `finish_reason=cost_cap`
on every cycle and never make progress.

## Decision

### New module: `chimera/core/cost_estimate.py`

Two dataclasses + two helpers:

```python
@dataclass
class TaskCostEstimate:
    task_text: str
    tier: str            # haiku | sonnet | opus
    model_id: str        # cheapest rung in that tier (after ADR 0072)
    estimated_cycles: int
    estimated_usd: float
    used_history: bool
    n_historical_cycles: int
    prior_failures: int

@dataclass
class InboxCostEstimate:
    tasks: list[TaskCostEstimate]
    total_usd: float
    total_cycles: int
    n_tasks: int


def estimate_task_cost(db, task_text, *, history=None, default_tier="haiku")
    -> TaskCostEstimate

def estimate_inbox(db, inbox_path, *, default_tier="haiku")
    -> InboxCostEstimate
```

The estimator anchors to historical data when available and falls
back to tier-typical token shapes when not:

1. **Predicted starting tier** via
   `chimera.core.escalation.recommended_tier()` — already applies
   the research-task floor (ADR 0075) and prior escalation
   memory (ADR 0046).
2. **Resolved model_id** via `chimera.providers.tiers.select_rung()`
   — picks the cheapest qualifying rung. After ADR 0072 this means
   `opus` tier → `deepseek-v4-pro`, not `claude-opus-4-7`.
3. **Per-cycle cost lookup**:
   - If `api_calls` has cycles for that `model_id`, take the median
     per-cycle spend.
   - Otherwise, fall back to tier-typical token estimates:
     - haiku → 8K in / 1.5K out
     - sonnet → 15K in / 3K out
     - opus → 25K in / 5K out
   - Multiply by the current price table.
4. **Cycles needed**: `1 + count of prior failures` on similar
   signatures (Jaccard overlap ≥ 0.5, same heuristic as
   `recommended_tier`).
5. **Per-task estimate**: per_cycle × cycles_needed.

### New CLI verb: `chimera estimate`

```
chimera estimate [--json] [--tier haiku|sonnet|opus]
```

Text output:

```
chimera estimate  3 open task(s)
  total estimate     $   0.23  over ~3 cycle(s)
  per-cycle cap      $2.00
  rolling-hour cap   $20.00

  [ 1] $   0.00  tier=haiku   cycles=1  (tier-typical)  deepseek-v4-flash
        Refactor module A
  [ 2] $   0.00  tier=haiku   cycles=1  (tier-typical)  deepseek-v4-flash
        Refactor module B
  [ 3] $   0.23  tier=sonnet  cycles=1  (tier-typical)  deepseek-v4-pro
        Research and write a citation-heavy section…
```

Warnings emitted on:
- Any task whose per-cycle projection exceeds the cycle cap (will
  trip on every cycle without progress)
- Total projection exceeding the rolling-hour cap (back-to-back
  cycles may trip rolling_hour_cap)

JSON mode emits the same data as a structured payload for shell-loop
guards or CI integration.

## Tests

`tests/test_cost_estimate.py` — 8 tests:

- No history → tier-typical fallback hits expected $ for haiku
- Research keywords → tier="sonnet", model_id=deepseek-v4-pro
- Three historical cycles → median used (verifies amortisation)
- Prior failure → estimated_cycles += 1, tier promoted
- Empty INBOX → zero
- Done tasks skipped
- Multiple tasks summed; research costs more than refactor
- Overnight-burn synthetic INBOX projects < $5 total (proves the
  v4.53 ladder inversion shrinks projections too, not just runtime)

Full suite after v4.59: 627 passing (was 619, +8 new).

## Non-goals

- **Not an exact predictor.** Cycle cost depends on round count,
  tool fan-out, continuation context size, and whether the cycle
  trips a cap. The estimator's job is to be useful, not perfect.
  Heuristic on; if operators want a tighter prediction they can
  use historical median by adding more cycles to api_calls.
- **No dependency-aware cost.** The estimate treats each task as
  running once. If task A's output feeds task B (and B needs less
  context as a result), we don't model that.
- **No model-switch sensitivity.** If the operator overrides the
  ladder via env, the estimate uses whatever `select_rung` returns
  today, not what it might return at run time. That's the closest
  thing to honest.
- **Not surfacing the estimate from the dashboard yet.** The CLI
  is enough for the prospective loop; a widget version of this is
  a natural follow-up.

## Why this shape

Why a separate module instead of putting it in budget.py? Because
the estimator needs to call `recommended_tier`, `select_rung`,
`parse_inbox`, and `_price_table` — three different concerns. A
dedicated module keeps the import surface honest and prevents
budget.py from accumulating responsibility for forward-looking
work.

Why median per-cycle cost instead of mean? Because cost is
right-skewed (a few very long cycles drag the mean up) but the
operator's question is "what does a typical cycle look like."
Median answers that better. Mean would also be reasonable; median
is the safer default.

Why `1 + prior_failures` cycles instead of something fancier?
Because that's exactly what the escalation memory already does in
practice: each failed cycle promotes the tier, so the next cycle
re-attempts at the promoted tier. The cycles needed roughly equals
the number of promotions plus one for the final attempt. More
sophisticated models (Bayesian completion-time priors,
signature-similarity weighting) would be premature without operator
signal that the simple model under- or over-counts.

Why include `prior_failures` in the output? Because it's the most
actionable diagnostic: a task with 3 prior failures is the one
the operator should rewrite, not just queue again.
