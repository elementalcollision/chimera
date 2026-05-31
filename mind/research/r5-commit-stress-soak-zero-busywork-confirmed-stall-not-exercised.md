# R5 commit-stress soak — zero-busywork guarantee CONFIRMED; prolonged stall NOT exercised

**Date**: 2026-05-31
**Soak**: `chimera-soak/v46-soakreport-2026-05-31-0058`
**Base**: main @ `e2442fb` (PR #187 — R5 `CHIMERA_SUPPRESS_PROPOSALS`, ADR 0151)
**Mode**: genuine rebuild + `CHIMERA_SOAK_BARE_COMMIT=1` (bare-shell commit, no
git_commit tool) + `CHIMERA_SOAK_AUTOCOMMIT=0` (no harness rescue)
**Verdict**: R5's suppression held deterministically (zero busywork, ledger-
verified) — but the run did **not** reproduce a prolonged stall, so the case R5
exists to defend was only lightly exercised. ADR 0151 stays **Proposed**.

## Intent

R4 (#185) made the self-commit re-soak #4 converge on iteration 1, so mechanism
C (planner/engines spawning governance busywork while a commit is pending) never
got to fire there. This soak was set up to reproduce re-soak #2's exact
conditions — bare-shell commit (the affordance the agent avoids), no harness
rescue — so phase 2 would run MANY iterations with a commit pending, the only
condition under which C fires. With R5 active, the prediction was: same 58×-style
stall, but a clean ledger (zero busywork).

## Result — two findings

### 1. R5 held (confirmed, deterministic)

Every phase-2 cycle logged `PLAN: skipped (proposals suppressed — commit-only
phase)`. The phase-2 ACT trace contains ONLY the two operator INBOX tasks (the
gated-test re-run + the bare-commit task) — **zero** `src: planner` tasks, zero
pre-commit-hook / CONTRIBUTING / CHANGELOG / githooks proposals (re-soak #2 was
flooded with these). The suppression is a hard gate and the ledger proves it
held while a commit was pending.

### 2. The stall did NOT reproduce (the caveat)

Phase 2 **converged in 2 iterations** — the agent self-committed via a bare
shell `git commit` (`48af729 [agent] create chimera/soak_report.py`;
`harness-autocommit` count 0, so the agent did it, not the harness). This is the
opposite of re-soak #2, where the same bare-commit affordance produced a 58×
`commit_not_executed` idle to `no_forward_progress`. So the prolonged-stall case
— where busywork would accumulate over ~45 cycles — was never created, and R5's
value under that case is therefore **not** empirically demonstrated here.

## The unresolved question

Why did the agent bare-commit on iteration 2 here when it idled 58× in re-soak
#2? Two hypotheses, indistinguishable from one run:

- **(H1) R5 helped the commit land.** With the busywork attractor suppressed,
  the only open task was the commit, and the agent did it. In re-soak #2 the
  bare-commit task was *interleaved* with planner busywork the agent kept
  chasing; here it stood alone. If true, mechanism C was never just noise — the
  busywork actively pulled the agent *off* the commit, and removing it aids
  delivery. This would make R5 a *positive* lever, not merely a hygiene gate.
- **(H2) Variance / substrate drift.** Re-soak #2 ran on an earlier main; this
  ran on a main with several merged fixes. The bare-commit avoidance is a
  stochastic behaviour that may simply not reproduce reliably; the 2-iteration
  convergence could be unrelated to R5.

H1 is *suggestive* — the clean single-task trace is consistent with it — but a
single run cannot separate it from H2. Asserting H1 would over-claim.

## Why the ADR stays Proposed

ADR 0151's acceptance criterion is "a commit-stress soak showing zero busywork
proposals while a commit is pending." Read narrowly, this run met it (zero
busywork, commit pending across 2 cycles). But the *spirit* — confirming R5
matters under the prolonged stall it was built for — was not exercised, because
the commit landed fast. Honest falsification practice: hold the ADR at Proposed
until a soak that genuinely stalls (so busywork *would* pile up) shows the ledger
staying clean across many cycles.

## What a decisive validation needs

A phase 2 that is GUARANTEED to run many iterations with a commit pending,
independent of agent behaviour. Options:

- **Forced-unsatisfiable commit**: make the commit impossible to land (e.g. a
  charter/scope condition the agent can't satisfy, or commit capability removed)
  so phase 2 idles to max iterations — then confirm zero busywork across ~45
  cycles. Artificial, but it deterministically exercises the stall.
- **A genuinely weaker commit tier** that reliably fumbles the commit for many
  cycles (less controllable).

Either would also help separate H1 from H2: if a forced-stall run with R5 OFF
spawns busywork and the same run with R5 ON does not, the suppression's value is
proven directly; and re-running the bare-commit avoidance N times would show
whether the 2-iteration convergence repeats (H2) or was a one-off.

## Setup artifact

The `CHIMERA_SOAK_BARE_COMMIT` runner knob (default off) added for this run
swaps the phase-2 INBOX to the bare-shell-commit form. It lands with this
capstone as reusable stress scaffolding — zero behaviour change off-knob — ready
for the forced-stall follow-up. `bash -n` clean.

## Status

- R5 suppression: **confirmed working** (deterministic, zero busywork while a
  commit was pending).
- R5 under prolonged stall: **not yet exercised** → ADR 0151 stays Proposed.
- Follow-up: a forced-stall stress soak (above), ideally A/B (R5 off vs on), to
  decisively validate and to separate H1 from H2.
