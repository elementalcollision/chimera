# v44 R2: the honesty gate's act_cycles/spend_usd MOVING-TARGET deadlock

**Date**: 2026-05-30
**Surfaced by**: v44 soak (`v44-soaksummary-2026-05-30-1317`) — the FIRST real
feature build. Chimera authored a correct `chimera/soak_summary.py` (6/6) but
phase 2 never committed.
**Scope**: in-loop honesty gate (Rules D/E numeric checks) — NOT a build defect.

## The finding

The module was correct and the postmortem was written, yet the soak FAILED to
converge. Ledger evidence:

- finish_reasons: `3 postmortem_dishonest`, `8 skipped_three_strikes`,
  `3 artifact_missing`, `1 syntax_invalid`, `1 stop`.
- postmortem claimed `act_cycles: 4` / `spend_usd: 0.14`, verdict `PARTIAL`
  ("untracked, uncommitted").
- ground truth at run-end: ledger `act_cycles: 16`, spend `$0.25`.
- the module + postmortem ended STAGED but never committed; phase 2 exited
  `no_forward_progress` after 29 iters.

## Root cause — a moving target, amplified by the #163 fallback

Two coupled defects in the post-#158/#163/#164 honesty gate:

1. **Rule D/E compared a SNAPSHOT against a GROWING ledger.** `act_cycles` is
   read once (via `summarize_run`) when the agent writes the postmortem, but
   the ledger grows by one record every ACT cycle — and postmortem-writing
   itself churns (here: 8 `skipped_three_strikes`). So a fixed claim of `4`
   was checked against a ledger that climbed 4 → … → 16. **No fixed value can
   satisfy a gate whose ground truth the very act of retrying inflates.**

2. **The #163 git-status fallback re-scanned the UNCHANGED postmortem every
   cycle.** It was built to fire when `write_targets` is empty by scanning
   `git status` for changed `.md` files. But a staged-not-committed postmortem
   shows as changed on EVERY phase-2 cycle, so the gate re-evaluated the same
   `09:29`-written file on each `09:32…09:47` cycle (the file's mtime predates
   phase-2 start — it was never re-written). A one-time write-time check became
   a permanent per-cycle commit blocker.

Together: every commit-cycle re-tripped `postmortem_dishonest` on the stale
`act_cycles: 4`, and every retry grew the ledger, widening the gap. Deadlock.

The irony: the feature under construction — `chimera soak summary`, which prints
these numbers authoritatively — was blocked by the exact numeric-honesty problem
it exists to solve. And the gate we made non-dormant the night before (#163/#164)
was now strict enough to block a *correct* build.

## The fix — OVER-claim-only

Rules D and E now hard-block ONLY over-claiming: claiming MORE cycles/spend than
the ledger/DB records (impossible without inflation). Under-claiming is
tolerated because it is either (a) a stale snapshot — legitimate, cycles accrue
after the read — or (b) build-cycles ⊆ all ACT records — a defensible narrower
metric. Neither is the dangerous "inflate the accomplishment" dishonesty.

Why this dissolves the deadlock: a growing ledger only WIDENS the under-claim
allowance, never narrows it. The gate can never become unsatisfiable by churn,
and the #163 fallback's per-cycle re-scan of an under-claiming postmortem keeps
PASSING. The genuinely dangerous dishonesty — claiming success that did not
happen (`tests_passing`, `verdict: CONVERGED`) — stays a hard TWO-sided gate
(Rules A–C, unchanged).

The cumulative-reporting CONVENTION (template + runner INBOX) is unchanged: the
agent should still report the run total. The gate's leniency is a safety valve
against the moving-target deadlock, not license to estimate.

## This reconciles the long-running tension

v41 originally judged `act_cycles`/`spend_usd` "too racy for an in-loop gate"
and deferred them. The drift chip (#158) made them HARD two-sided gates; v43
showed they fire; v44 showed a hard two-sided numeric gate DEADLOCKS a churning
run. Over-claim-only is the synthesis: numeric claims are gate-checked against
the only thing that is unambiguously dishonest (inflation), while the racy
direction (under-count vs a growing ledger) is left to the operator review and
the now-buildable `chimera soak summary` tool.

## Next

- This chip lands the over-claim-only Rules D/E + updated tests + this note.
- Then **re-run v44** on the de-deadlocked substrate — the correct module
  (6/6) should now commit, since an honest cumulative (or conservative)
  `act_cycles` no longer perpetually re-trips the gate.
