# ADR 0024 — ACT ladder escalation under retry (v3.11)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0001](0001-sdk-chimera.md) §"Model tier ladder", [ADR 0019](0019-provider-retry-backoff.md)

## Context

v3.5 added in-rung retry/backoff for transient provider errors. When
those retries exhaust, the exception bubbled out of
`complete_with_tools`, and the ACT executor recorded
`outcome=non_retriable` and gave up. That made the ladder system
ornamental — it picked a rung but never escalated past it.

## Decision

`chimera.providers.tiers` gains a sibling helper:

- `eligible_rungs(tier, *, requires_tools=False, prefer_cheapest=True)`
  returns the full ordered list of rungs satisfying the request.
  `select_rung` becomes `eligible_rungs(...)[0]`.

`ActExecutor.execute` (in `chimera/core/act.py`) now:

1. Materialises the eligible-rungs list at the start of the run.
2. Filters to rungs whose provider is actually configured.
3. On `complete_with_tools` exception: records the api_call row,
   records `outcome=retry_exhausted` (not `non_retriable`), advances
   to the next rung, and re-enters the same round. No exponential
   backoff between rungs — the in-rung `retry_call` already paid
   that cost.
4. When all rungs are exhausted, returns `finish_reason="provider_error"`
   with the last error message.

## Why "retry_exhausted" not "non_retriable"

`retry_call` only re-raises after it has used its retry budget on
classifiable transient errors, OR it re-raises immediately on a
permanent error. Either way, by the time ACT sees the exception, this
rung is done. `retry_exhausted` is the honest label and lets the
dashboard distinguish "tried hard, gave up" from "didn't try".

(Permanent errors still escalate. That's intentional: a 401 on
OpenRouter doesn't tell us anything about Anthropic's auth, and the
ladder exists precisely to route around per-provider failures.)

## Non-goals

- No adaptive rung selection from history (Reggio-style). Still pure
  cheapest-first walk.
- No per-tier escalation budget. The walk is bounded by the ladder
  length (currently 3 rungs).
- No streaming changes. Streaming still doesn't retry; ladder
  escalation only applies to `complete_with_tools`.

## Tests

`tests/test_act.py`:
- `test_act_records_failure_outcome_on_provider_error` updated — all
  ladder outcomes now record `retry_exhausted`, length ≥ 1.
- New `test_act_escalates_to_next_rung_on_first_rung_failure` —
  OpenRouter rung raises, Anthropic rung succeeds, executor reports
  completed=True and the outcomes table shows
  `["retry_exhausted", "success"]`.

Full suite: 447 passing.
