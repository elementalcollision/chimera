# v46 — PARTIAL: trio capstone built + 3 fixes confirmed; phase-2 commit stall surfaced

**Date**: 2026-05-30
**Soak**: `chimera-soak/v46-soakreport-2026-05-30-1812`
**Charter**: `mind/research/v46-soakreport-design.md`
**Verdict**: **PARTIAL** — the module was authored correct (4/4) and STAGED, but
phase 2 stalled without committing. Operator-landed (the work is done; only the
commit mechanics failed). The third real feature; first multi-module build.

## Outcome: PARTIAL (did not self-converge)

The agent's own postmortem is honest: `verdict: PARTIAL`, "written to disk and
tested but never git add'ed or committed... a manual commit closes the gap." The
module is correct (4/4, composes the two cores); the soak did not produce the
commit. This chip lands it manually.

## The three friction fixes — all CONFIRMED in-loop

| Fix | Signal (this run) | Prior |
|---|---|---|
| #168 over-claim-only | **0 `postmortem_dishonest`** — honest PARTIAL | v44-#1 deadlocked |
| #174 witness asymmetric | **0 `witness_rejected`** on the correct diff | v42/v43/v44 churned |
| #177 churn fix | **0** postmortem-churn `artifact_missing` — the 1 `artifact_missing` was a failed *haiku build* attempt (cycle 146), NOT the postmortem; the `mind/soak/<run-id>/` directory false-positive is gone | 2–3 every soak |

The friction-free substrate held exactly as designed.

## The NEW finding — phase-2 commit stall

With the three known frictions gone, the next limiting factor became visible.
Phase 2 (commit-only) ran **30 iterations for $0.028** — it flatlined:

- An early `scope_evasion` at cycle 156 (write_targets empty — the agent claimed
  action without writing) appears to have started a three-strikes skip loop.
- The cycle counter advanced (156 → 176) but spend did not move — the agent was
  cycling on skipped/empty cycles, not doing real work.
- The files ended STAGED (`git add`'d) but never committed; phase 2 exited
  `no_forward_progress`.

So: **the agent staged the files but the `git commit` never executed, and a
single early scope_evasion derailed phase 2 into a no-progress stall.** This is
the next R2 target — phase-2 commit reliability. (Filed as a follow-up chip.)

Notable secondary: the cheap haiku tier produced 0 working code in cycle 146
(scope_evasion → artifact_missing) before the pro tier wrote it correctly in
cycle 147 — a tier-quality signal, not a substrate defect.

## The module + verb

`chimera/soak_report.py` composes v44's `format_iteration_table` and v45's
`format_finish_reason_breakdown` under one headline — clean, typed, module-level
imports (the first build to import existing Chimera modules). `chimera soak
report <run-id>` renders the full soak-health view (verified end-to-end).

## What this chip lands

- `chimera/soak_report.py` (authored, verbatim + provenance).
- `chimera/cli.py` — `chimera soak report <run-id>` leaf wrapper.
- `tests/test_soak_report.py` — un-gated; 5 tests (4 contract + 1 CLI guard).
- `mind/research/v46-soakreport-{postmortem,capstone}.md`.

## Next

- **R2: phase-2 commit stall** — diagnose why the commit didn't execute and why
  an early scope_evasion derails phase 2 into a no-progress stall. The
  artifact-detail (#173) + a commit-attempt trace will pinpoint it on the next
  soak. This is the new limiting factor for clean convergence.
