# v35 soak postmortem — attempt #4

**Date**: 2026-05-28
**Soak runner**: `scripts/long_cycle_soak_v35.sh`
**Branch**: `chimera-soak/v35-2026-05-28-1327` (off main @ `1ce575e`)
**Worktree**: `/Users/dave/chimera-soak-v35-2026-05-28-1327`
**Run log**: `state/long_cycle_v35_2026-05-28-1327.log`
**Outcome**: operationally PASS, substantively FAIL, **terminated early by operator** at phase 1 iter 7.

This attempt's purpose was to exercise the five hardening fixes that closed the v35-postmortem ladder (PRs #103, #105, #108, #109, #110) and the wiring-coordinator clarification (#111) under the original v35 charter — diagnose F2's −10.42pp temporal-reasoning regression.

## TL;DR

- **5/5 hardening fixes that *could* be exercised at phase 1 behaved correctly.** No false positives, no crashes, no missed signals on the events they were designed to catch.
- **One new gap surfaced**: the forward-progress watchdog (PR #109) watches `(cycle, spend)`. In attempt #4 every iteration advanced both — yet zero tasks completed. The watchdog cannot catch this failure mode.
- **Substantive verdict: hard FAIL.** Zero design notes produced, zero hypothesis classifications produced, zero commits attempted across 7 iters / 29 min / $1.00 spend. The agent flailed on the same hypothesis-classification task as attempt #3 — but now each ACT phase was correctly capped at 240s by PR #110 rather than burning for 2017s.
- **Operator terminated the run** at iter 7 once the degenerate pattern was confirmed, sparing ~3h and ~$9 of additional spend.
- **`wiring_coordinator` question definitively closed by PR #111** (merged during the run): the misleading INBOX prose was stripped and replaced with honest manual-handoff language. The coordinator script remains a standalone, manually-invokable tool — no auto-push, no auto-PR, no auto-merge.

## Substantive layer

### Phase 1 design recommendation (R1 / R2 / R3?)

**Not produced.** The agent never reached the point of writing the design note `mind/research/v35-locomo-temporal-regression-design.md`. Across 7 phase-1 iterations the ACT phase was cancelled by the 240s budget every single time with `completed=0/N tasks`.

### Hypothesis classification table

**Not produced.** Iter 5 ACT showed the agent attempting "for each regressed item, classify into H1/H2/H3/H4-other" but hitting `max_rounds (rounds=18, tools=37, completed=False)` before the budget axe fell. No regressed-items sample was committed to disk.

### Phase 2 outcome

**N/A — phase 2 never started.** Operator killed the run during phase 1.

### Auto-generated PR

**None.** Per PR #111, this is now the documented expected behavior — the runner stops at the sentinel and leaves the branch for manual review.

### Was the LoCoMo temporal-regression diagnosis actually produced?

**No.** Four supervisor-driven attempts at this question have now failed:

| Attempt | Substantive result | Failure mode |
|---|---|---|
| #1 (PR #102) | None | ADR 0141 guard misfired on every secondary worktree |
| #2 (PR #104) | None | Persistent loop crossed SQLite thread boundary |
| #3 (PR #106) | MIXED — confabulated diagnosis | Agent produced a recommendation, but its citations did not match the data; pre-commit scope check (#108) was the response |
| #4 (this) | None | Agent ACT-phase locked at budget cap with 0 tasks completed; operator-terminated |

The chartered question — *what is causing the −10.42pp temporal-reasoning regression?* — remains open after four attempts. See "Recommended next chip" below.

## Operational layer

### Wall-clock and spend

- Phase 1: **7 iters, 29 min wall, $1.0051 of $5.00 cap** before operator-terminate
- Phase 2: did not start
- Total: ~$1.00 spent

Each phase 1 iter consumed almost exactly 240002–240005ms of ACT (i.e. the budget) plus ~5ms of overhead, yielding a steady ~4.3 min/iter cadence and ~$0.22/iter average burn.

### Per-guard observations

| Guard | PR | Verdict | Evidence |
|---|---|---|---|
| ADR 0141 detector (`--git-dir` vs `--git-common-dir`) | [#103](https://github.com/elementalcollision/chimera/pull/103) | **PASS** | Preflight in secondary worktree reported `worktree_branch_drift ok ... secondary worktree`; no false-positive across 29min of operation. |
| Persistent-loop SQLite thread fix | [#105](https://github.com/elementalcollision/chimera/pull/105) | **PASS** | Soak ran 7 iters with no `SQLite objects created in a thread can only be used in that same thread` exception. WAL checkpoint on SIGTERM succeeded (`received signal 15; checkpointing WAL and exiting`). |
| Pre-commit scope check (ADR 0146) | [#108](https://github.com/elementalcollision/chimera/pull/108) | **N/A** | Zero commits were attempted across the run (no ACT phase reached the commit step), so the guard had nothing to evaluate. `state/scope_check_events.jsonl` was never created. Static-unit coverage from PR #108 itself remains the only attestation. |
| Forward-progress watchdog | [#109](https://github.com/elementalcollision/chimera/pull/109) | **PASS-but-blind** *(see gap below)* | Watchdog did not fire. Per its definition (N consecutive iters with unchanged `(cycle, spend)`), this is correct: cycle advanced 0→146→147→148→149→150→151 and spend advanced $0.00→$0.02→$0.25→$0.55→$0.61→$0.83→$1.01 across iters 1–7. The watchdog's signal is structurally unable to detect "every iter consumes budget but completes zero tasks". |
| ACT-phase budget enforcement | [#110](https://github.com/elementalcollision/chimera/pull/110) | **PASS** | **6/6** ACT phases observed in the log were cancelled at 240002–240005ms with the structured event `ACT phase budget exceeded: cancelled at 240s (completed=0/N tasks)`. Iter 5 additionally exhibited the `max_rounds (rounds=18, tools=37, completed=False)` precondition that motivated the budget. Phase progression to WRITE/FLUSH/COMMIT/ROTATE proceeded cleanly under cancellation. Backward-compat default (240s) used; `CHIMERA_ACT_BUDGET_SECONDS` not overridden. |
| `wiring_coordinator` prose strip | [#111](https://github.com/elementalcollision/chimera/pull/111) | **N/A (this run)** | Merged at 13:53:54Z, mid-run. Soak was launched at 13:27 from `1ce575e` (pre-#111). Change is confined to phase-2 INBOX prose; soak never reached phase 2. Verdict on the wiring_coordinator question itself is resolved by codebase inspection — see dedicated section below. |

### Witness panel verdicts; engine-guard fires; trust delta

- Phase 1 engines OFF (per charter) → no engine-guard activity expected; none observed.
- Trust tier held at T5 throughout (`chimera trust degrade-check: ok baseline=T5 current=T5 drop=0 threshold=2` after every iter).
- No witness-panel charter extraction reached: this only fires in phase 2 ([long_cycle_soak_v35.sh:454–476](scripts/long_cycle_soak_v35.sh#L454-L476) territory).

### New gap surfaced: forward-progress watchdog signal mismatch

PR #109's watchdog tracks `(cycle, spend)` and fires after N consecutive iters with both unchanged. This was designed against attempt #3's behavior, where the agent stalled with a stuck spend signal.

Attempt #4 exhibited a **different** degenerate mode: every ACT phase consumed the full 240s budget and was cancelled, advancing cycle (149→150→151) and spend ($0.61→$0.83→$1.01) every iter — while completing **zero** tasks. The watchdog cannot fire on this mode by construction.

The right signal for this mode is **per-iter completed-task delta**, not `(cycle, spend)` delta. A trivial extension to the watchdog: also track `tasks_completed_this_iter` from the ACT-budget-exceeded structured event; fire if `completed=0/N` repeats for N consecutive iters even if cycle/spend advance.

This is a candidate **ladder #6** chip — see "Recommended next chip".

## `wiring_coordinator` observation — load-bearing for the operator decision

**Conclusion: definitively closed by PR #111 during this run.**

### Pre-run inspection (the finding that motivated #111)

`grep -rn "wiring_coordinator" scripts/` confirmed:

- `scripts/wiring_coordinator.sh` exists as a real implementation: push + auto-PR + auto-merge for sequential-decomposition soaks.
- `scripts/long_cycle_soak_v35.sh` (pre-#111) referenced "wiring_coordinator" **only inside the agent-facing phase-2 INBOX heredoc** at line 488: *"The wiring_coordinator handles push + PR + merge on a successful soft-sentinel exit."*
- No actual invocation of `wiring_coordinator.sh` exists in `long_cycle_soak_v35.sh`, `_soak_common.sh`, or `soak_lib.sh`.
- On `soft_sentinel_deliverable_landed`, the runner's actual behavior is: `break` out of `phase_loop`, log post-run summary (`git log main..HEAD`, `chimera cost`, `ls mind/research/`), exit. **No push. No PR. No merge.**
- The misleading prose had been copy-pasted across the v25–v35 runners (verified via the archive scan).

### PR #111 resolution

Merged at 13:53:54Z (option B from the supervisor's pre-finding). The phase-2 INBOX heredoc now reads:

> *"After a successful soft-sentinel exit the runner stops with the branch left in the worktree for manual operator review — the operator inspects the diff (`git log main..HEAD`), cherry-picks or discards as appropriate, and opens any resulting PR by hand. There is NO auto-push, NO auto-PR, NO auto-merge."*

The change also updates `scripts/long_cycle_soak_v34.sh` and adds a `scripts/archive/soak-runners/README.md` note documenting the historical misleading language. `scripts/wiring_coordinator.sh` itself is retained for its legitimate sequential-decomposition use case but is no longer referenced by the soak charter.

### Operator decision (ladder #5) — closed

The pre-merge analysis recommended option B (strip the lie); PR #111 implemented exactly that. No further wiring_coordinator action is required from this postmortem.

## Comparison to prior attempts

| Attempt | Wall | Spend | Reached phase 2? | Substantive output | Blocker / outcome |
|---|---|---|---|---|---|
| #1 (relaunch #102) | <1 min | $0 | No | None | ADR 0141 false-drift in secondary worktree — fixed in PR #103 |
| #2 (relaunch #104) | minutes | $0 | No | None | Persistent loop SQLite thread mismatch — fixed in PR #105 |
| #3 (final #106) | full run | full caps | Yes | MIXED — confabulated | Agent produced unsupported citations — pre-commit scope check PR #108 + watchdog PR #109 + ACT budget PR #110 |
| **#4 (this)** | **29 min** | **$1.00** | **No (op-killed)** | **None** | **Agent ACT-phase locked at budget; 0/N tasks completed; forward-progress watchdog blind to this mode** |

Attempts #1 and #2 surfaced infrastructure defects; attempt #3 surfaced a confabulation defect; attempt #4 surfaces a **convergence defect** (the agent cannot complete a task within 240s under the chartered prompt, regardless of how many iterations it gets).

## Closing the v35-postmortem cycle?

**Partially.** The five-fix ladder closed in PRs #103/#105/#108/#109/#110 + the #111 clarification has eliminated every previously-observed *operational* failure mode of the soak loop. Attempt #4 confirmed those fixes work as designed.

But attempt #4 also surfaces a **fifth class of defect** that the existing ladder does not cover: the agent can fail to converge on the chartered task while every operational guard remains green. PR #109's watchdog, PR #110's budget, and PR #108's commit-scope check all behave correctly under this failure mode — but none of them detect it.

**The v35 substantive charter (LoCoMo temporal-regression diagnosis) is unresolved after four supervisor-driven attempts.** Re-chartering the same question a fifth time without changing the input shape would likely produce the same result.

## Honest disclosures

- The run was **operator-terminated**, not naturally completed. Phase 2 was never exercised. The PR #111 prose change had zero observable effect on this run's data.
- The **5/5 hardening-fix PASS verdict only applies to phase-1 surface area**. Phase-2-only behaviors (witness panel charter extraction, soft-sentinel exit handling, scope-check on real commits) were not exercised here.
- The **forward-progress-watchdog "PASS-but-blind"** rating is generous: the watchdog did exactly what it was specified to do, but the spec turns out to be insufficient for the failure mode actually observed. If the operator preferred, this could be re-rated **MISS**.
- The **ACT-budget "PASS" verdict** is on cancellation mechanics, not on whether 240s is the right cap. Six consecutive iters at exactly 240s with zero completions suggests 240s is not enough for the chartered classification task — but raising the cap without a forward-progress signal would just burn more money on the same flailing.
- **Substantively, this attempt produced nothing**. No design note. No hypothesis table. No diagnosis. No commit. The hardened operational stack worked perfectly while the agent produced zero useful output. That is the honest summary.

## Recommended next chip

Two candidates, in priority order:

1. **Ladder #6: extend forward-progress watchdog with completed-task signal.** Track `tasks_completed_this_iter` (parseable from the existing `ACT phase budget exceeded: cancelled at 240s (completed=K/N tasks)` event). Fire watchdog if `K == 0` for N consecutive iters even when cycle/spend advance. Small scoped change (~30 LOC in [scripts/soak_lib.sh](scripts/soak_lib.sh) + a test). Closes the convergence-defect blind spot exposed by attempt #4.

2. **Move off the v35 chartered question.** Four attempts have failed; the chartered question may be poorly shaped for the autonomous loop (too much retrieval re-running required per item, no per-step checkpointing within ACT). Consider re-shaping the v35 charter into a smaller atomic unit (e.g. "classify 5 regressed items, write one paragraph, commit") — or move on to non-v35 work and revisit LoCoMo temporal regression via a directed human-driven analysis instead of a soak.

The operator's `wiring_coordinator` decision (ladder #5) is already closed by PR #111. No action needed on that front.
