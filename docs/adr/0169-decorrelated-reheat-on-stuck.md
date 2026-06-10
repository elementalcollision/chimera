# ADR 0169 — Decorrelated reheat-on-stuck (annealing restart, v4.120)

**Status:** Proposed (2026-06-08); Amended (2026-06-09) — see "Amendment: NameError non-start" below

## Amendment (2026-06-09) — NameError non-start when the flag is enabled

**Symptom.** The 2026-06-09 routing soak campaign
([routing-soak-campaign-2026-06-08.md](../../mind/research/routing-soak-campaign-2026-06-08.md),
§"CRITICAL FINDING") found that the all-flags envelope made **0 LLM calls** in
6/6 runs — `chimera run` failed *before* ACT's first provider call, so the agent
never acted, edited, or committed. Every non-all-flags run converged normally.

**Root cause (this ADR's flag).** The "Decision → Code" note below states the
failure count is "computed just above the ladder-walk site." That was wrong: the
ladder walk lives in `ActExecutor._execute_inner`, but `decision =
remediation_decision(...)` is a local of the *separate* outer method
`ActExecutor.execute`. The wired guard

```python
if anneal_reheat_enabled() and decision.matched_failures > 0:
```

therefore raised **`NameError: name 'decision' is not defined`** the moment
`anneal_reheat_enabled()` returned `True` — `and` short-circuits, so Python only
evaluated `decision.matched_failures` once the flag was on, and the attribute
access raised *before* the `> 0` comparison (so it failed on the very first
attempt, prior failures or not). The exception propagated out of `execute` →
`_phase_act` → the ACT-budget `wait_for`, aborting ACT with zero provider calls.
This is **CHIMERA_ANNEAL_REHEAT-attributable alone**; it only stayed hidden
because every converging soak cell used only TOOL_PREFILTER / COMPLEXITY_ROUTING,
never ANNEAL_REHEAT, and the full unit suite never exercised the PLAN→ACT setup
path with the flag on.

**Fix.** Thread the count explicitly: `_execute_inner` takes a new
`matched_failures: int = 0` parameter, `execute` passes
`matched_failures=decision.matched_failures`, and the guard/log/`reheat_count`
inside `_execute_inner` use that parameter instead of the out-of-scope
`decision`. Behaviour is otherwise unchanged: flag off, or `matched_failures == 0`,
is byte-identical to the cheapest-first walk.

**Regression coverage.** `tests/test_act.py::test_act_anneal_reheat_reaches_provider`
sets `CHIMERA_ANNEAL_REHEAT=1` and asserts `execute()` reaches the provider
(≥1 call) instead of raising — closing the live-loop gap the unit suite missed.

**Live validation (2026-06-10, post-fix).** Two-part:

1. *Envelope composes:* the full all-flags `real_task_soak`
   (`realtask-2026-06-10-0915`) converged end-to-end — 32 api_calls, agent
   self-commit, gate PASS — with the reheat path correctly idle (no prior
   failures). See the campaign doc's post-fix validation section.
2. *Rotation fires:* a controlled live exercise seeded ONE real prior failure
   (`max_rounds` at tier haiku) for a task signature, then ran ACT against real
   providers twice. Flag OFF: escalation memory promoted haiku→sonnet and the
   lead call went to `deepseek/deepseek-v4-pro` (cheapest-first, unrotated).
   Flag ON, same seed: the `annealing reheat — rotating ladder by 1 (lead
   vendor minimax/minimax-m3)` log fired and the real provider call went to
   `minimax/minimax-m3`. This also confirms the "Non-goals" composition claim
   live: tier promotion picks the *ladder*, reheat picks the decorrelated
   *lead* within it.

**Status:** Proposed (2026-06-08)

## Context

The tier ladder is a simulated-annealing schedule in disguise: the cheap,
diverse, cross-vendor haiku/sonnet rungs are **high temperature** (broad,
cheap, noisy exploration); opus is **low temperature** (precise, expensive
exploitation). The within-tier walk (`eligible_rungs`, `providers/tiers.py`)
is always **cheapest-first**, so a task signature that keeps failing re-tries
the *same lead vendor* every cycle — e.g. `deepseek-v4-pro` first on every
sonnet attempt. That is correlated failure: the model that just failed gets
first crack again.

The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
(§3b, ranked #4) names the fix from annealing: when a signature is stuck,
**reheat to a decorrelated restart** — jump to a *different-vendor* rung rather
than strictly the same one. A `deepseek→minimax` switch decorrelates failure
modes far more than `deepseek→deepseek-bigger`. The `SONNET_LADDER`'s
deliberate cross-vendor spread already gestures at this; annealing names *why*
and *when*.

The "stuckness" signal already exists: `remediation_decision`
(`core/remediation.py`) returns `matched_failures` — the count of prior
same-signature escalations — and ACT already computes it just above the
ladder-walk site. And every rung in a tier ladder is a **distinct vendor**
(sonnet: deepseek, minimax, glm, qwen, mistral, gemini, anthropic), so simply
*rotating* the cheapest-first order by the failure count lands a different
vendor in the lead each stuck cycle.

## Decision

A pure rotation helper plus a flag-gated wiring at the ACT ladder walk.

### Code

- `chimera/providers/tiers.py`:
  - `anneal_reheat_enabled()` — honours `CHIMERA_ANNEAL_REHEAT` (default off;
    same parsing shape as `peer_selection_enabled`, ADR 0167).
  - `rung_vendor(rung)` — vendor namespace (`deepseek/...` → `deepseek`; bare
    `claude-*` → `anthropic`).
  - `decorrelated_rung_order(tier, *, reheat_count, requires_tools)` — **pure**:
    cheapest-first `eligible_rungs` rotated by `reheat_count` positions so a
    fresh vendor leads. The full ladder is preserved (rotation wraps) so every
    rung stays available as a fallback. `reheat_count <= 0` returns the
    unrotated order — byte-identical to `eligible_rungs`.
- `chimera/core/act.py` — at the rung-walk construction: when
  `anneal_reheat_enabled()` and `decision.matched_failures > 0`, build the rung
  list from `decorrelated_rung_order(..., reheat_count=decision.matched_failures)`
  instead of plain `eligible_rungs`; otherwise unchanged. The existing
  provider-availability filter is applied after.

### CLI / dashboard

None. Operator surface is the `CHIMERA_ANNEAL_REHEAT` flag. With the flag off,
or on the first attempt at a signature (`matched_failures == 0`), the ladder
order is byte-identical to the v4.120 path.

## Tests

`tests/test_anneal_reheat.py` — 14 cases: flag parsing; `rung_vendor`
namespaces; the SONNET ladder's rungs are verified to be distinct vendors (the
property the decorrelation relies on); `reheat_count=0` is byte-identical to
`eligible_rungs`; reheat rotates the lead vendor (exactly a rotation by 1);
successive reheats give distinct leads; rotation preserves the full rung set;
`reheat_count` wraps modulo (a full rotation returns the original order);
negative count is unrotated; the `requires_tools` filter is respected. Existing
`test_task_escalation`, `test_complexity_routing`, `test_act_remediation`, and
`test_act_force_model` stay green (69 across the slice).

## Non-goals

- **Tier promotion.** This reheats *within* a tier (decorrelated restart at the
  same temperature); the haiku→sonnet→opus escalation memory
  (`recommended_tier`, ADR 0075/0166) is unchanged and still runs first. Reheat
  composes with it: the (possibly promoted) tier picks the temperature, reheat
  picks a decorrelated vendor at that temperature.
- **Random selection.** The rotation is deterministic in `reheat_count` for
  reproducibility and testability; a true random reheat (seeded RNG) is a
  trivial follow-up behind the same call.
- **Per-rung outcome tracking.** Recording which specific vendor failed for a
  signature (vs the count) would let reheat *exclude* the failed vendor rather
  than rotate past it; deferred — the rotation already avoids the just-failed
  lead because adjacent rungs differ.

## Why this shape

Rotation by the existing `matched_failures` count is the minimal faithful
encoding of "reheat on stuck": it needs no new state (the failure count is
already computed for remediation), it is byte-identical at zero reheats, and it
exploits a property the ladder already has (distinct vendors per rung). Keeping
the helper pure mirrors ADR 0167/0168 — the annealing logic is unit-tested
without a provider call, and ACT's change is a guarded few-line swap at one
site.
