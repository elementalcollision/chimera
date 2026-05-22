# ADR 0103: Phase-scope fix-without-test detection

**Status:** Accepted
**Date:** 2026-05-22
**Version:** v4.99
**Related:** ADR 0099 (per-task fix-without-test), ADR 0102 (operator-side
submit-pr), soak v9 post-mortem
(`mind/postmortems/soak-v9-2026-05-22.md`, Failure B).

## Context

v4.92's `check_fix_without_test` runs **per-task**: it inspects the
write_targets a single task produced and fires if `chimera/X.py` was
written without a `tests/test_*.py` sibling in the same task. That
contract is intentional — it gives fast feedback inside the ACT loop —
but soak v9 exposed a structural blindspot.

Soak v9 phase 2 INBOX split the work across two tasks:

| Task | Text | write_targets | Per-task v4.92 |
|---|---|---|---|
| A | "Implement the fix" (chimera/core/act.py) | `[chimera/core/act.py]` | fires within task A — but task A was *allowed* to ship without a test because task B owns the test |
| B | "Write a regression test in `tests/test_loop_guard.py`" | `[]` (agent claimed done, wrote nothing) | clear (no chimera/ touched) |

The agent's two `[agent]` commits landed `chimera/core/act.py +15 lines`
with `tests/` untouched across the entire branch. Per-task v4.92 saw
each task in isolation and the cumulative branch state violated the
"fix needs a test" invariant.

Worktree fixture preserved at
`/Users/dave/chimera-soak-v9-2026-05-22-1554` — branch has the exact
shape: chimera/core/act.py touched, tests/ empty, two `[agent]` commits.

## Decision

Add a **phase-scope** variant that runs at the phase boundary against
the cumulative branch diff, alongside (not instead of) the per-task
detector. Two-layer defense:

1. **Per-task** (`check_fix_without_test`, v4.92): catches the obvious
   case quickly inside the loop. Fast feedback, immediate remediation.
2. **Phase-scope** (`check_phase_fix_without_test`, v4.99): catches the
   split-task case at phase end by re-applying the same rule to the
   cumulative `git diff main..HEAD --name-only` output.
3. **Pre-PR gate** (already shipped in v4.97 `submit_pr.validate`,
   ADR 0102): the same check applied at the LAYER closest to the
   reviewer, refusing to open the PR if `chimera/X.py` is touched
   without `tests/test_*.py`.

New `finish_reason`: `phase_fix_without_test`. Registered in
`ESCALATING_FINISH_REASONS` and in `FINISH_REASON_TRUST_DELTAS` at
**1** (moderate; same severity as the per-task variant — incomplete
delivery against a specified contract).

### Why a separate finish_reason instead of a `scope` field

Considered: extend the existing `fix_without_test` with a `scope`
metadata field on `ActResult`. Rejected because:

- Trust-decay deltas are keyed by `finish_reason` string in
  `FINISH_REASON_TRUST_DELTAS`. Adding a scope tag would require
  fan-out across the trust manager, escalation memory, and the
  three-strikes counter.
- The two signals fire at different layers (loop-internal vs.
  phase-boundary) and from different callers (ACT vs. runner). Keeping
  them distinct in the table makes the escalation history queryable
  ("which phase-boundary gates have fired in the last N soaks?")
  without parsing metadata.
- The per-task and phase-scope cases have different *remediation
  hints*: per-task ⇒ "patch the named source AND its test now";
  phase-scope ⇒ "the BRANCH lacks a test for the source edit you
  shipped — write the test before the operator opens the PR."

## Consequences

- Bash soak runners can invoke the phase-scope check at the end of
  `phase_loop` by computing `git diff --name-only main..HEAD` and
  shelling out to a Python one-liner or by recording the result in the
  escalation memory directly. The function is exposed as
  `chimera.core.act.check_phase_fix_without_test`.
- v4.97's pre-PR gate already enforces the same rule at submit time —
  this ADR's runtime detector is upstream of that, so an agent that
  trips phase-scope but recovers (writes the test in a later task)
  produces a clean PR.
- The phase-scope check is **deliberately not** a per-cycle gate. The
  cumulative diff is meaningful only at phase boundaries; running it
  per-task would re-fire on every cycle until the test lands, drowning
  the escalation log.

## Implementation notes

- Excluded sources (`chimera/_version.py`, `chimera/__init__.py`) match
  the per-task detector exactly.
- A "test" means a path under `tests/` whose basename starts with
  `test_`. `tests/helpers.py` does not satisfy the gate.
- Soak v9 fixture is the regression test
  (`test_phase_scope_per_task_blindspot_soak_v9` in
  `tests/test_act_completeness.py`).
