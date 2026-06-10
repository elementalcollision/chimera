# ADR 0173 — Soak-task scope adherence is advisory, not gated

**Status:** Proposed (2026-06-10)

## Context

Cell 6 of the routing soak campaign
([routing-soak-campaign-2026-06-08.md](../../mind/research/routing-soak-campaign-2026-06-08.md))
surfaced a contract gap: a self-determined soak agent fixing "9 ruff findings
in `chimera/core/act.py`" also landed an **unrequested refactor** (extracting
`decision.matched_failures` into a threaded parameter) in the same commit. The
verify gate enforces GREEN, the critic gate enforces FAITHFULNESS, and the
ADR 0146 pre-commit scope check binds only to a chip's
`## READY-FOR-REMEDIATION` allowlist — **nothing enforces adherence to a
soak task's stated scope.** The campaign posed the choice: add a soak-task
scope guard, or accept that "green + faithful" is the real contract and scope
is advisory.

Evidence gathered since:

- **The creep was stochastic, not structural.** Cell 7 (baseline, same
  harness, enforced critic) produced a perfectly in-scope single-commit fix;
  cells 1–3 and the 2026-06-10 post-fix all-flags run were likewise clean.
  One creep in ~10 converging runs is model variance, not a systemic leak.
- **The creep was *correct*.** Cell 6's unrequested refactor was, in
  substance, the same fix later root-caused and landed by a human-reviewed PR
  (#279) for the ADR 0169 NameError non-start. A hard scope gate would have
  blocked a behavior-preserving change that anticipated a real bug fix.
- **The safety floor never depended on scope.** Across the whole campaign —
  including 6 broken-envelope runs — no unfaithful or red change ever became
  a commit. The binding contracts (verify-green, critic faithfulness, trust
  tiers, cost caps, ADR 0146 for chips) held without a scope gate.
- **Every soak commit is operator-reviewed before merge.** The
  manual-handoff discipline (no auto-push/PR/merge) means scope creep is
  visible at exactly the point a human adjudicates it — cell 6's creep was in
  fact caught there, by reading the diff.

## Decision

**Scope adherence for soak/self-determined tasks is ADVISORY.** The binding
commit contract remains: verify GREEN + critic FAITHFUL + trust/cost gates +
(for chip remediation) the ADR 0146 allowlist. No new blocking gate is added.

What "advisory" means operationally:

1. **Surfaced, not blocked.** Out-of-scope hunks in a soak commit are a
   review finding for the operator at manual handoff, not a refusal at
   commit time. The soak reports/characterization tables SHOULD note
   scope-exceeding diffs (as the campaign's cell 6 row did).
2. **ADR 0146 is unchanged.** Chip remediation keeps its binding
   `## READY-FOR-REMEDIATION` scope gate — that path locks scope by design
   because the design phase already adjudicated it.
3. **Re-evaluation trigger.** If scope creep is ever implicated in a
   *faithfulness* failure (a creep the critic approved that turned out to be
   behavior-changing), this decision is to be revisited — that would falsify
   the "green + faithful suffices" premise this ADR rests on.

## Non-goals

- **A diff-vs-task-text classifier.** Deciding mechanically whether a hunk
  "serves" a natural-language task is the same hard problem the critic gate
  already approximates; duplicating it as a blocking gate would double the
  false-reject surface for marginal benefit.
- **Loosening chip scope.** The ADR 0146 gate stays binding where it applies.

## Why this shape

A gate earns its place when the failure it blocks is one the existing
contracts let through *and* the cost of a miss is high. Cell 6's miss cost
was a messier diff and confusing provenance — caught by the human review the
workflow already requires — while the one observed "creep" was a correct fix
the project later wanted. Blocking that class of change spends false-rejects
to prevent a failure mode with no observed harm. Advisory surfacing keeps the
information without the gate.
