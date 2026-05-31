# R5 forced-stall A/B — mechanism C proven, R5 validated under a real stall

**Date**: 2026-05-31
**Soaks**: arm A `v46-soakreport-2026-05-31-1435` (R5 OFF), arm B
`v46-soakreport-2026-05-31-1302` (R5 ON, de-facto)
**Base**: main @ `049f644` (PR #189 — `CHIMERA_SOAK_FORCE_STALL` lever)
**Verdict**: **R5 (ADR 0151) validated.** Under a deterministically forced
prolonged stall, R5 OFF spawned 63 governance-busywork tasks; R5 ON spawned
zero. The difference is deterministic and large — mechanism C is real, R5
suppresses it, and variance (H2) is ruled out. ADR 0151 → Accepted.

## Why this run existed

The earlier commit-stress soak
(`r5-commit-stress-soak-zero-busywork-confirmed-stall-not-exercised.md`) showed
R5's suppression held but the agent self-committed in 2 iterations, so the
PROLONGED stall — the case R5 defends — was never exercised. The open question
was H1 (R5 helped the commit land) vs H2 (variance). The fix: make the commit
*unsatisfiable* (`CHIMERA_SOAK_FORCE_STALL=1`, PR #189) so phase 2 idles to the
budget cap regardless of the agent, and run R5 off vs on.

## Result — the A/B

Both arms: genuine rebuild + bare-shell commit + autocommit off + force-stall.
The ONLY difference is `CHIMERA_SUPPRESS_PROPOSALS`.

| Arm | R5 | phase-2 cycles | spend | `proposals suppressed` PLANs | `src:planner` busywork tasks |
|---|---|---|---|---|---|
| A (control) | OFF (`0`) | 32 (budget-capped) | $1.56 | 0 | **63** |
| B (treatment) | ON (default) | 150 (budget-capped) | $0.75 | 149 | **0** |

### Control (R5 OFF) — mechanism C, vividly

8 proposal-adding PLAN cycles; **63** governance-busywork ACT tasks. Verbatim
samples:

- "Add an entry to CHANGELOG.md summarizing the soak report script addition"
- "Read mind/research/…postmortem.md and capture any action items as discrete
  tasks"
- "Push the commit to the remote repository" (×4 phrasing variants — the planner
  hallucinating a commit to push while the real commit was force-blocked)
- "Append a summary of the soak report output to the postmortem"

This is exactly the re-soak #2 pattern: with the commit stuck, the planner/
engines fill the void with concrete, safe, "helpful" governance work that has
nothing to do with the one deliverable.

### Treatment (R5 ON) — clean

Every one of 150 stall cycles logged `PLAN: skipped (proposals suppressed —
commit-only phase)`. Zero busywork. Phase 2 idled cheaply to the budget cap.

## What it proves

- **Mechanism C is real and large.** 63 busywork tasks under stall with R5 off.
- **R5 suppresses it completely.** 0 under stall with R5 on, across 150 cycles.
- **H2 (variance) is ruled out.** The control/treatment difference is
  deterministic (a hard gate) and an order of magnitude, not noise. (H1 — "R5
  helps the commit *land*" — remains a separate, untested claim; this A/B is
  about busywork suppression, which is now proven.)
- **Bonus: cost.** The control burned **2× the budget in 1/5 the cycles** ($1.56
  / 32 vs $0.75 / 150) — proposal + engine calls are expensive, so R5 also
  sharply cuts spend during a stall.

## Harness bug found + fixed

The first control attempt silently ran *suppressed*: phase 1 does `unset
CHIMERA_SUPPRESS_PROPOSALS` (engines off), so phase 2's
`${CHIMERA_SUPPRESS_PROPOSALS:-1}` re-defaulted to 1 — the operator's `=0` never
survived phase 1. Caught by reading the ledger (it logged "proposals
suppressed" in the supposed control). Fixed: the runner now captures the
operator value once at startup into `OPERATOR_SUPPRESS_PROPOSALS` and reads that
in phase 2 (`"${OPERATOR_SUPPRESS_PROPOSALS:-1}"`). Verified: operator `0` →
phase 2 `0`; unset → `1`. The mis-run was not wasted — it served as a clean
arm-B (R5 ON) data point (150 cycles, 0 busywork) and is the arm B above.

## Status

- ADR 0151 → **Accepted** (validation section added).
- R5 commit-phase mechanism C: **closed and proven**.
- The forced-stall lever (`CHIMERA_SOAK_FORCE_STALL`) + the operator-override fix
  are reusable for any future suppress-style A/B.

## The whole v46 commit-phase arc (closed)

scope_evasion unmask (#180) → commit-not-executed detector (#181) → harness
commit (#182) → avoidance analysis (#183) → phase-1 witness fix (#184) → atomic
git_commit tool (#185) → self-commit confirmed (#186) → suppress-proposals
(#187) → stress capstone (#188) → forced-stall lever (#189) → **this A/B (R5
proven)**. Every diagnosed avoidance mechanism (A/B/D via R4, C via R5) is now
both closed and empirically validated.
