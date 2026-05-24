# ADR 0114: Autonomous-delivery contract

**Status**: Operational (atomic tier) · Emerging (composed tier) — amended 2026-05-24
**Date**: 2026-05-23 (original) · 2026-05-24 (two-tier amendment + results sweep)
**Soaks**: v17, v18, v19, v21, v25, v26, v27, v28, v29, v30 (atomic) · v4.116 wiring (composed)

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

---

## 2026-05-24 amendment — two-tier framing + results sweep

The original "N ≥ 5" criterion in [Success criterion](#success-criterion)
treated all shippable targets as one population. After [docs/wiring-decomposition-methodology.md](../wiring-decomposition-methodology.md)
shipped, the soak series demonstrated that multi-file *wiring* tasks
behave differently from single-function *atomic* targets. This
amendment splits the criterion into two tiers and records the current
result.

### Tier definitions

- **Atomic** — single-file / single-function / single-line targets
  that fit the v17–v18 shape. Each verbatim-merged `[agent]` commit
  counts as 1. **Bar: N ≥ 5.**
- **Composed** — multi-file coordinated wiring tasks shipped via the
  decomposition methodology. The composite (all sub-soaks shipping
  verbatim through the coordinator's auto-merge gate) counts as 1.
  **Bar: N ≥ 3.**

A composed delivery's constituent sub-soaks ALSO count toward the
atomic tier. (e.g. v4.116's five sub-soaks v25–v29 contribute 5 to
atomic and 1 to composed.)

### Verbatim-merge definition

Per the original criterion: the agent's `[agent]`-prefixed commit
was merged unchanged. Operator-side fixes *after* the merge
(separate follow-up PRs) do not retroactively disqualify the ship —
those become their own atomic-tier observations. The contract is
about the merge act, not the long-term defect rate of the shipped
code.

### Results sweep (as of 2026-05-24)

#### Atomic tier: **N = 10** (≥ 5 ✓ — operational)

| Soak | PR | Shape | Verbatim merge? | Notes |
|---|---|---|---|---|
| v17 | #7 | add-one-function (orphan-worktree) | ✓ | Original ADR baseline |
| v18 | #8 | add-one-function (prune_escalations) | ✓ | Original ADR baseline |
| v19 | — | (referenced in methodology doc) | ✓ | — |
| v21 | — | (referenced in methodology doc) | ✓ | Template for v25+ runners |
| v25 | (squashed) | add-field (ActResult charter_file_count_violations) | ✓ | First sub-soak of v4.116 |
| v26 | #22 | add-call-site | ✓ | Follow-up chip #23 caught a missing constructor wire-through; not a patch-on-merge |
| v29 | #30 | add-remediation-hint | ✓ | Manually shipped after a coordinator hang (pre-watchdog retrofit) |
| v27 | #37 | add-escalation-entry | ✓ | First auto-merge via wiring_coordinator |
| v28 | #38 | add-trust-delta | ✓ | Shipped with silent `-1` sign-flip; PR #39 fixed as a separate atomic |
| v30 | #42 | add-test-file (coverage hardening) | ✓ | Charter drift on layer count; PR #44 extended as a separate atomic |

#### Composed tier: **N = 1** (≥ 3 — emerging)

| Wiring target | Sub-soaks | Coordinator clean? | Notes |
|---|---|---|---|
| v4.116 (charter_file_count detector) | v25 + v26 + v29 + v27 + v28 (5/5 shipped) | ✓* | *v28's sign-flip was a layer-5 defect inside an otherwise verbatim composite. Strict reading: still counts (each sub-soak merged verbatim); cautious reading: composed-tier defect rate ≠ 0 and N=3 should reset if a future composite has a layer-defect class regression. |

Two more composed wirings needed to clear the N ≥ 3 bar.

### What changed in detection vs. the original ADR

Components 1–3 unchanged. Additions since 2026-05-23:

- **v4.115** — `commit_message_diff_drift` (rooted-path discipline)
- **v4.116** — `charter_file_count` (this composite)
- **v4.117** — Trust-T0 commit gate (blocks agent git commit/push at T0)
- **v4.118** — `provenance_claim_invalid` (cited versions/ADRs resolve)
- **v4.119** — Sticky detector-finding demotes (no auto-promote after a detector-induced demote)
- **v4.120** — Soak-runner watchdog (kills mid-cycle hangs)

These weren't required for the original v17/v18 demonstration but
materially shape the failure modes the contract now covers. The
v28 sign-flip is the kind of bug that the original 3-component
chain could not have caught (the diff was structurally valid and
the tests passed); it surfaced through the v4.116 composite
itself misbehaving in production usage. This argues for a future
**Component 4** in this ADR: composed-tier defect detection (e.g.
property-test the wiring as a unit).

### Revised open questions

1. (Closed) ~~Should there be a separate ADR per target-class?~~
   Answer: no — a single results table in this ADR is sufficient
   when the tiers and shapes are tagged. Re-open if shapes
   proliferate beyond ~8.

2. **New**: How should the contract handle defects discovered
   *after* a verbatim merge that were caused by the merged code?
   v28's sign-flip is the canonical example. Current stance:
   the merge act still counts as verbatim; the defect becomes
   its own atomic-tier observation (PR #39 here). But this
   inflates atomic counts artificially when a defect cascade
   produces multiple follow-up PRs. Worth revisiting if seen
   again.

3. **New**: Should the composed tier's N reset when a composite
   ships with any sub-component defect, or only when the
   composite as a whole fails to merge? Current stance: count
   the merge (N=1 for v4.116). Revisit if a future composite
   has a defect cascade larger than v4.116's single sign-flip.
