# ADR 0050 — DEGRADE-path trust drill (v4.28)

**Status:** Accepted (2026-05-19)

## Context

The v4.26 trust drill exercised REFUSE (T0) and ALLOW (T2) but
skipped DEGRADE — the middle policy decision that says "proceed but
with the local context downgraded to T1." DEGRADE is the trickiest
path because the call still succeeds; only the dispatch context
changes. A bug in the DEGRADE branch would never surface as a
failed dispatch — only as a quietly-downgraded one.

## Decision

Extend `run_federation_trust_drill` with a third sub-run at
`current_tier=1`. The default policy has
`min_trust_tier_for_allow=2`, so T1 → DEGRADE. The sub-run asserts:

- decision is `DEGRADE` (read from the peer trust journal, since
  dispatch succeeds either way).
- the witness output still arrives (`research_target` present in
  text).
- the per-peer journal accumulates ≥ 3 entries (one per sub-run).

The drill now walks the full REFUSE → DEGRADE → ALLOW ladder against
the same peer subprocess. The `_one_run` helper was refactored from
a `seed_healthy: bool` flag to a `tier: int` parameter; ts=0 means
"no file" (default T0), ts>=1 writes a fresh `trust_state.json`.

## Tests

`tests/test_federation_trust_drill.py::test_trust_drill_walks_refuse_degrade_allow`
replaces the prior two-decision test. Asserts all three decisions
and the witness signal through the DEGRADE path.

Full suite: 526 passing, 5 skipped.
