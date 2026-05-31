# v46 re-soak #4 — GENUINE autonomous self-commit via the git_commit tool

**Date**: 2026-05-31
**Soak**: `chimera-soak/v46-soakreport-2026-05-31-0012`
**Base**: main @ `f31acf3` (PR #185 — the atomic `git_commit` tool, ADR 0150)
**Mode**: genuine rebuild (`CHIMERA_SOAK_STRIP_TARGETS`) + **`CHIMERA_SOAK_AUTOCOMMIT=0`**
**Verdict**: **R4 confirmed.** The agent self-committed via `git_commit` on the
first call and phase 2 converged — the first end-to-end autonomous delivery
(author → stage → green → self-commit) in the entire arc, with the harness
commit OFF.

## The experiment

The whole commit-phase arc converged on one falsifiable question: does giving
the agent a single blessed atomic commit tool overcome the commit avoidance, or
will it skip `git_commit` the same way it skipped the bare `git commit`? This
re-soak ran that test directly — strip the targets (genuine rebuild), wire the
phase-2 INBOX to use `git_commit`, and turn the harness-commit fallback OFF so
the only way to converge is the agent committing itself.

## Result — it self-committed

```
phase1 → built chimera/soak_report.py, test 4/4 green, postmortem written
phase2 iter 1:
  Re-run gated test                       → 4 passed
  "Commit … in ONE step with git_commit"  → stop, tools=1, completed=True
  phase2 end: soft_sentinel_deliverable_landed   ← CONVERGED in 1 iteration
```

Hard verification:

- **`harness-autocommit` log count: 0** — the harness did not commit; autocommit
  was off. This was the agent.
- The commit: `3141352 [agent] create chimera/soak_report.py`, diff scoped to
  `chimera/soak_report.py` + `mind/research/v46-soakreport-postmortem.md`.
- **Zero `commit_not_executed` firings** in phase 2 (re-soak #2 had 58).
- Post-soak primary gate **5 passed**; verdict-honesty ground truth **true**.
- Converged at cycle 156, **total spend $0.14**.

The agent made **one** tool call in the commit task (`tools=1`) — the same
one-action-then-stop behaviour that previously left it staged-but-uncommitted —
but this time that one action was `git_commit`, which *is* the whole ritual, so
it landed.

## The decisive contrast

| Re-soak | Commit affordance | Phase-2 outcome |
|---|---|---|
| #2 | bare `git commit` (shell) | 58× `commit_not_executed` → no_forward_progress |
| #3 | harness commits (ADR 0148) | converged — but the harness did it |
| **#4** | **`git_commit` tool, autocommit OFF** | **agent self-committed → converged** |

Same agent, same provider, same task, same avoidance of the bare shell
`git commit` — the *only* variable that changed between #2 and #4 is the shape of
the affordance. That isolates the cause: the avoidance was never an inability or
a refusal; it was **single-shot under-execution (D) + staging-≈-done (A) +
gate-induced risk aversion (B)** (per
`why-the-agent-avoids-git-commit-2026-05-30.md`). Collapsing the commit ritual
into one blessed, obviously-safe tool call dissolved all three at once:

- **D** — one call completes stage → commit → verify, so the one-action tendency
  now *lands* the commit instead of stopping at a read.
- **A** — the tool's success IS the commit; there is no staged-but-uncommitted
  intermediate to mistake for done.
- **B** — the gated complexity sits behind a single affordance the agent treats
  as safe rather than a risky free-form incantation.

(Mechanism **C**, planner meta-work amplification, never got a chance to fire —
the commit landed on iteration 1, before the planner could spawn governance
busywork.)

## What this does and does not claim

- **Does**: demonstrate genuine autonomous *delivery* — the agent authored,
  staged, greened, and committed its own work, with every commit gate intact
  (the tool routes through the gated shell path) and the harness fallback off.
- **Does not**: claim the agent will self-commit with the *bare* shell
  `git commit` — it still won't; the win is the affordance, not a change in the
  underlying disposition. Nor does it address mechanism C in cases where the
  commit doesn't land on the first iteration.

## Arc complete

The v46 commit phase is closed end-to-end:

1. #180 — scope_evasion on-disk guard (unmask the commit phase).
2. #181 (ADR 0147) — commit-not-executed detector (make the skip loud).
3. #182 (ADR 0148) — harness-executed commit (route around; validated).
4. #183 — commit-avoidance analysis + the four-mechanism diagnosis.
5. #184 (ADR 0149) — phase-1 postmortem witness false-positive.
6. #185 (ADR 0150) — atomic `git_commit` tool.
7. **this re-soak** — genuine autonomous self-commit, **confirmed**.

## Follow-ups (logged, not chased)

- **Mechanism C** — quiet the discovery/curiosity/reflection engines during the
  commit-only phase so a non-first-iteration commit can't be out-competed by
  governance busywork. The complement to R4.
- Generalise the `git_commit` INBOX wiring beyond the v46 charter if the tool is
  adopted for other build soaks.
