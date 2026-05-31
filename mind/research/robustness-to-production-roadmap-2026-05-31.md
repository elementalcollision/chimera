# Roadmap: from "it works once" to robust & production-worthy

**Date**: 2026-05-31
**Context**: Chimera now runs the full self-authored loop live — originate
(self-charter) → verify (teeth) → build → deliver (self-commit or harness). The
teeth gate discriminates correctly (accepts byte-format 0.90 / IPv4 1.00; rejects
"make the codebase better" / "improve performance"). This roadmap is the path
from *demonstrated* to *trustworthy in production*.

## What is proven vs what is not

**Proven (live):** self-charter; teeth gate (accept/reject discrimination);
materialize; build from scratch; self-commit via `git_commit` (pure loop) AND
harness-commit fallback; every v46 commit gate; the falsification/soak discipline.

**Not yet robust / production-worthy:**
1. Builds run against a *self-authored* test, not the *real* repo (its tests,
   linter, type-checker, CI).
2. One new module per charter — no multi-file / cross-module changes.
3. Delivery stops at a branch in a worktree — no real PR, self-review, or
   review-comment loop.
4. Weak/rejected charters are dropped — no critique-and-revise.
5. No outcome telemetry — "did the merged change do what it claimed?"
6. The generic build runner is young (one real bug already found — the phase-2
   INBOX checkbox); convergence/sentinel timing is fuzzy (`no_forward_progress`
   exits even after success).
7. Charter gate is untested on *hard-to-test* goal classes (randomness, I/O,
   time, network, concurrency) where a discriminating test is itself hard.

## Tier A — make the loop we built RELIABLE (close reliability gaps)

The loop works; make it trustworthy enough to lean on. Smallest, highest-confidence.

- **A1. Generic-runner hardening + sentinel fix.** The phase-2
  `no_forward_progress`-after-success is a convergence-detection gap (the soft
  sentinel should exit cleanly when the `[agent]` commit lands). Tighten it; add
  more dryrun/integration tests for the runner. *Falsify:* a successful build
  exits `soft_sentinel_deliverable_landed`, never `no_forward_progress`.
- **A2. Charter gate on hard-to-test goal classes.** Run the gate on randomness /
  time / I/O / network goals; confirm it either rejects (can't write a
  discriminating test) or the charterer produces a *seam* (inject the clock/RNG)
  that IS testable. *Falsify:* "generate a random UUID" is rejected OR the
  charter injects a seedable RNG and scores teeth ≥ 0.8.
- **A3. Critique-and-revise on weak charters.** When teeth < threshold, feed the
  surviving mutants back to the charterer for one revision pass before dropping.
  *Falsify:* a borderline goal that fails at 0.6 passes after one revise.

## Tier B — PRODUCTION-VALUE capabilities (the real leap)

- **B1. Build against the REAL test suite (S5).** Instead of a pre-written
  charter test, let Chimera iterate a change against the *actual* repo tests +
  ruff + type-check, fixing real failures it did not author. This is the
  difference between "passes the test we gave it" and "makes the codebase
  better." *Falsify:* a real flaky-test fix or dep bump that greens real CI.
- **B2. Multi-file / cross-module changes (S4).** One charter → edits across ≥2
  files with the scope check + multi-target verification. *Falsify:* a change
  that edits A and updates B's caller, both verified.
- **B3. Real delivery surface (S7).** Open a real PR with a defensible
  description, a self-review summary, and a risk assessment; respond to review
  comments. *Falsify:* a human can act on the PR in 30s without spelunking.
- **B4. Outcome telemetry (S9).** After a merge, track post-merge signal (CI
  stayed green, the metric moved, the fix held). Close the loop on *value*, not
  just *delivery*. *Falsify:* a dashboard row per shipped change with its outcome.

## Tier C — PRODUCTION POSTURE (how much rope, on what)

- **C1. Trust-tiered autonomy policy (S8).** Compose the existing primitives
  (trust state, scope check, witness panel, the two commit paths) into a policy:
  which outputs ship self-committed vs harness-committed vs human-gated, keyed on
  trust tier × blast radius. *Falsify:* a low-tier or high-blast-radius change is
  forced to human-gate; a high-tier low-blast one self-ships.
- **C2. Shadow mode on a real repo (S6).** Point Chimera at genuine low-risk
  maintenance on a real project; human reviews every PR before merge. The first
  literally-production-valuable output, behind a human gate.
- **C3. Self-improvement loop (the end state).** Chimera self-charters fixes to
  ITS OWN substrate (the codebase it runs on) — build → self-commit → operator
  lands. An agent that hardens itself. (Highest value, highest risk — gated hard
  by C1.)

## Recommended order

A1 → A2 → A3 (reliability first; cheap, high-confidence) → B1 (the production
leap: real tests) → B3 (delivery surface) → C1 (autonomy policy) → C2 (shadow
mode) → B2/B4/C3 as the surface matures.

**Start with A1** — the sentinel/convergence gap is the one concrete reliability
defect already observed; fixing it makes every subsequent build run trustworthy.

## The honest production bar

A self-charter → build → self-commit agent on a real codebase is only
production-worthy when: (a) it builds against real verification (B1), (b)
delivery is human-reviewable (B3), (c) autonomy is tiered by blast radius (C1),
and (d) outcomes are measured (B4). The judgment + deterministic-gate pattern
that carried the commit-phase and originated-judgment arcs is the same pattern
every item above should follow — pair each new capability with a gate that makes
its failure mode loud and deterministic.
