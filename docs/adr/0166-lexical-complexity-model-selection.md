# ADR 0166 — Lexical task-complexity model selection (v4.120)

**Status:** Accepted (2026-06-10) — live-fire validated in the 2026-06-08/10
routing soak campaign: complexity floor decisions observed live (trivial task →
floor None, stayed cheap; hard task → floor sonnet) across converging cells and
the post-fix all-flags envelope; no convergence regression. See
[routing-soak-campaign-2026-06-08.md](../../mind/research/routing-soak-campaign-2026-06-08.md).
Default remains OFF (`CHIMERA_COMPLEXITY_ROUTING`).

## Context

The vLLM Semantic Router evaluation
([semantic-routing-evaluation-2026-06-06.md](../research/semantic-routing-evaluation-2026-06-06.md))
identified Chimera's **model selection** as a routing-shaped decision that
is lexical and brittle today. `core/escalation.py::recommended_tier`
chooses the starting tier (haiku/sonnet/opus) from two signals:

1. a token-bag **Jaccard overlap** against `task_escalations` history, and
2. `research_task_floor_tier` — a single hard-coded **keyword list** that
   floors *research-shaped* tasks to sonnet.

Both are narrow. A genuinely complex engineering task — *"refactor the
parser, then run the suite and write the report"* — matches none of the
research keywords and has no escalation history on its first attempt, so it
starts at haiku, fails, records an escalation, and only gets a capable model
on the **next** cycle. That is the exact "simple → fast path / complex →
reasoning" split the vLLM Semantic Router centres on, paid a cycle late.

[ADR 0123](./0123-honcho-inspired-enhancements.md) already added a manual
`ReasoningTier` knob (`budget.py`), but nothing *infers* it from the task.
This ADR adds the inferring classifier — the lexical "model selection"
first slice from the evaluation's §3.2, sequenced ahead of the
embedding-backed version that waits on [ADR 0134](./0134-hybrid-search-eval.md)
§"#6.b".

## Decision

A pure, embedding-free complexity classifier lifts the starting tier,
behind a default-OFF flag so routing is byte-identical until opted in.

### Code

- `chimera/core/escalation.py`:
  - `complexity_routing_enabled()` — honours `CHIMERA_COMPLEXITY_ROUTING`
    (default off; same shape as `tool_prefilter_enabled` / `hybrid_search_enabled`).
  - `_complexity_signals(task_text)` — returns `(reasoning_hits, breadth,
    multistep)`: whole-word engineering/reasoning-verb hits, distinct
    tool-type breadth groups, and multi-step decomposition (spelled-out
    phrasing, ≥2 numbered-list markers, or ≥2 path-like deliverables).
  - `complexity_floor_tier(task_text)` — maps those signals to a floor:
    `"opus"` on the steep high bar (a reasoning verb **and** multi-step
    **and** breadth ≥ 2, or ≥ 3 distinct reasoning verbs), `"sonnet"` on
    any single signal, else `None`.
  - `recommended_tier()` consults `complexity_floor_tier` **only** when the
    flag is set, applying it as a floor right after the research floor and
    before the escalation-memory walk. It can only ever *lift* the tier,
    never demote below the caller's default.

### CLI / dashboard

None. Operator surface is the `CHIMERA_COMPLEXITY_ROUTING` env flag.

## Tests

`tests/test_complexity_routing.py` — classifier cases (no floor / sonnet /
opus across reasoning-verb, breadth, multi-step, numbered-list, and
whole-word-match-not-substring inputs; flag parsing) plus `recommended_tier`
integration (flag off keeps default; flag on lifts to sonnet/opus; never
demotes below default; simple task stays put). Full slice
(`test_complexity_routing` + `test_task_escalation` + `test_research_tier_floor`):
56 passing.

## Non-goals

- **Embedding-based complexity scoring.** Deferred to ADR 0134 §"#6.b";
  `complexity_floor_tier` is the drop-in seam for that upgrade.
- **Replacing the escalation-memory promotion.** The Jaccard history walk
  stays as the cross-cycle net; this only improves the *first* attempt.
- **Default-ON.** The opus bar is steep on purpose (cost-runaway history,
  [ADR 0072](./0072-cost-runaway-guards.md)); shipping it off-by-default
  lets operators opt in knowingly, consistent with ADR 0165.
- **Tool selection.** Shipped separately in
  [ADR 0165](./0165-semantic-tool-prefilter.md).

## Why this shape

Floor-only (never demote) keeps the failure mode safe: a false-positive
costs a one-tier-too-high model on one task; a false-negative simply falls
back to the existing escalation-memory net. Whole-word reasoning-verb
matching avoids the substring trap (*"implementation"* mentioned in prose
is not *"implement the thing"*). The breadth grouping mirrors
`budget._TOOL_KEYWORDS` so the two task-shape heuristics read consistently.
