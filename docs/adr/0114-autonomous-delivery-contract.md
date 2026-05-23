# ADR 0114: Autonomous-delivery contract

**Status**: Accepted
**Date**: 2026-05-23
**Soaks**: v17 (PR #7, merged), v18 (PR #8, merged)

## Context

Across soaks v1–v16 each shippable PR required an operator code
intervention before merge — typically a one-line fix the
detection chain missed:

| Soak | PR | Operator intervention |
|---|---|---|
| v8 | #2 | Trim agent-added refactor of unrelated module |
| v9 | #3 | Remove out-of-charter doctor flag |
| v14 | #4 | Strip `--json` flag the charter explicitly forbade |
| v16 | #5 (closed) | Add missing `import re` after runtime NameError |

The pattern: agents produced *almost-shippable* diffs that needed
small operator-side patches to land. This made the soak series a
useful research instrument but not a delivery mechanism — every
shipped PR carried operator code in it.

Soaks **v17** (orphan-worktree detection, PR #7) and **v18**
(prune_escalations, PR #8) were the first two consecutive PRs
where:

1. The agent's `[agent]`-prefixed commits were merged **verbatim**.
2. The operator's contribution was limited to review, branch push,
   and merge — no code patches.
3. The detection chain rejected scope-creep attempts (v18 saw
   `scope_evasion ×2` and `test_claim_invalid ×2` fire after the
   in-charter deliverable shipped; none of the rejected drift made
   it into a commit).

This ADR names that pattern and defines the contract.

## Decision

We define the **autonomous-delivery contract** as the conjunction
of three platform components and one operator practice. When all
four are in place, a soak is expected to produce a shippable PR
with zero operator code patches.

### Component 1: Charter-anchored witness panel (v4.110)

The witness panel reviews each diff against the **task charter
text** rather than against a generic "does this look reasonable"
rubric. The charter is a numbered list of constraints (SCOPE,
SEMANTICS, PATTERN, prohibitions, etc.) passed alongside the
diff. The panel's decision is "does this diff violate any of
these N rules" — a decidable question with a small, fixed
search space.

### Component 2: Task-text charter extraction (v4.112)

The charter the panel sees is parsed directly from the INBOX
task text the agent reads. The two views are guaranteed to be
the same string. This closed the v14 gap where the agent
overshot a `--json` task because the panel was scoring against
an inferred charter rather than the operator-written one.

### Component 3: Test-claim invalid detection (v4.113)

When an agent claims a pytest run passed, the platform re-runs
the cited command from the operator side (`uv run pytest`) and
treats exit code 1 as `test_claim_invalid` (other exit codes
are environmental and skipped). This catches the v16 NameError
class where the diff was structurally clean but runtime-broken.

### Operator practice: charter-shaped INBOX

Soak runners write an INBOX with an explicit `CHARTER:` section
(numbered constraints) and an `OVERSHOOT TRAPS:` section
(specific scope-creep moves to reject). v4.112 extracts these
sections by name; the panel uses them verbatim. Soak runners
that omit a numbered charter cannot benefit from v4.110 anchoring.

## Success criterion

A soak series demonstrates the autonomous-delivery contract is
**operational** when:

> **N consecutive soaks ship a charter-clean PR with zero
> operator code interventions, where N ≥ 5.**

As of this ADR, N = **2** (v17, v18). The contract is
*emerging*, not yet *operational*. We expect to revisit this
ADR after v21 with one of:

- **Confirmed (N ≥ 5)** — promote to a documented platform
  capability; surface in `chimera doctor`; gate v5.0 release on
  it.
- **Refuted (a soak in v19–v21 needs operator patches)** —
  diagnose which component leaked; file a chip; demote the
  contract back to "research pattern."
- **Inconclusive** — extend the series.

## Anti-criteria — when the contract does NOT apply

The contract makes no claim about:

1. **Targets not expressible as a numbered charter.** Open-ended
   research tasks ("explore X", "find the best Y") have no
   decidable rubric for the witness panel.
2. **Cross-module wiring with implicit coupling.** Targets
   whose correctness depends on side-effects in modules the
   charter doesn't enumerate will leak.
3. **Targets larger than a single function or check.** v17 and
   v18 were both "add one function and its tests" shapes. The
   contract has not been demonstrated on multi-file features.
4. **Targets where test-claim validation cannot run.** If the
   targeted tests require expensive setup, GPU access, or
   external services, v4.113 will skip and the lying-about-tests
   class will leak.

## Consequences

### Positive

- Two PRs in a row shipped without operator patches. The soak
  series is now a delivery channel, not just a research one.
- The detection chain's behavior is empirically observable in
  SESSION_LOG.md (demote events with `finish_reason=` show
  exactly which detector caught what).
- Future detectors fit into a named framework — they're either
  charter-anchored (panel inputs), runtime-behavior (test-claim
  class), or structural (the existing chain).

### Negative

- The contract creates an expectation. A v19 that needs operator
  patches will be a louder failure than it would have been
  before this ADR.
- The "N ≥ 5" bar is a guess. If v17 and v18 were both
  structurally-easy targets and v19+ regress on harder shapes,
  the bar may need to discriminate by target class.
- Charter authoring is now a first-class operator skill. A
  badly-written charter (vague constraints, missing OVERSHOOT
  TRAPS) will not benefit from v4.110/112 even when the platform
  is correctly wired.

### Neutral

- This ADR does not change platform behavior — it documents a
  pattern that has emerged from existing components. No code
  changes accompany it.

## Related ADRs

- ADR 0110 — Witness charter anchoring (component 1)
- ADR 0112 — Task-text charter extraction (component 2)
- ADR 0113 — Test-claim invalid detection (component 3)
- (forthcoming) ADR 0115+ — broaden test-claim to non-pytest tools

## Open questions

1. Should `chimera doctor` add a check for "current branch's
   most recent soak landed without operator patches"? Would
   need a journal of which commits were `[agent]` vs.
   operator, which we don't track structurally today.

2. Should the soft-sentinel exit (scripts/soak_lib.sh,
   action item #1 from the v17+v18 retro) be a first-class
   part of the contract, or remain a runner-side optimization?
   Argument for promotion: it materially reduces the
   post-deliverable drift window where v4.113 has to fire
   defensively. Argument against: it's not what determines
   whether a PR is shippable, only how cheaply we got there.

3. When N reaches 5, do we need a separate ADR for each
   target-class the contract has been demonstrated on?
   (add-one-function, add-one-CLI-verb, add-one-check,
   add-one-test, etc.) Or a single update to this ADR with
   a results table?
