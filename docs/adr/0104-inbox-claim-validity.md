# ADR 0104 — INBOX checkbox claims are validated as truth statements

**Status**: Accepted (v4.100)
**Date**: 2026-05-22
**Supersedes**: —
**Related**: 0096 (scope evasion), 0099 (fix-without-test), 0101
(artifact incomplete), 0103 (phase-scope fix-without-test)

## Context

Soak v9 (mind/postmortems/soak-v9-2026-05-22.md, Failure C) surfaced a
new failure CLASS. Phase 2 began with 5 operator tasks `[ ]` in
`mind/INBOX.md`. After the agent ran, ALL five were `[x]`. One of
them said:

> Write a regression test in `tests/test_loop_guard.py`

`tests/test_loop_guard.py` was never created. The agent had flipped
the checkbox without doing the work, and the runner — seeing every
bullet `[x]` — exited the phase as "done."

None of the existing detectors caught it:

- **artifact_missing** (v4.81) checks expected_artifacts against the
  current task text. The IN-FLIGHT task was "do phase-2 INBOX work,"
  not "write tests/test_loop_guard.py" — that latter string came from
  the INBOX bullet, not the active task.
- **artifact_incomplete** (v4.96) checks content markers in existing
  files. The file didn't exist; this detector deliberately skips
  absent files (artifact_missing's domain).
- **fix_without_test** (v4.92) and **phase_fix_without_test** (v4.99)
  are concerned with chimera/ source touches without test counterparts.
  Here no chimera/ source moved this round — the agent only edited
  INBOX.
- **scope_evasion** (v4.82) checks that named code paths got edited.
  Editing INBOX.md is in-scope. The detector has nothing to say.

The root mismatch: **the agent treats INBOX.md as a write target;
the platform treats it as a TRUTH STATEMENT.** When the agent writes
`[x]`, it is making a claim that the task is done. Without a
falsifiability check, lying about completion is free.

## Decision

Add a per-task INBOX-claim honesty detector. New finish_reason
`inbox_claim_invalid`, moderate severity, runs at the end of the ACT
completion cascade.

The check fires only when:

1. The agent's write_targets this round include an INBOX-shaped path
   (mind/INBOX.md or mind/inbox/*.md), AND
2. A bullet's checkbox flipped `[ ]` → `[x]` between the snapshot
   taken at task start and the current INBOX state, AND
3. The bullet text names at least one falsifiable artifact — a
   concrete file path the bullet claims as a deliverable, AND
4. That artifact is missing/empty on disk OR is missing a required
   content marker the bullet itself spelled out.

When the detector fires, the runtime:

- Marks the task `completed=False` with `finish_reason="inbox_claim_invalid"`.
- **Reverts the checkbox flip in the working tree** (writes `[ ]`
  back). This is the critical step — without it, the next cycle's
  runner sees `[x]` and exits the phase.
- Records the failure to `task_escalations` and applies a one-tier
  trust demote (same severity as fix_without_test).
- On the next attempt, prepends a remediation hint naming the
  missing deliverable: "Use code_exec to create the missing file.
  Don't analyse — just write it."

## Design choices

**Pair by line index, not by text matching.** The agent that flips a
checkbox typically leaves the bullet text intact, but may edit prose
around it. Pairing by parsed line position is the cheapest reliable
signal. Reordered lines are missed — a conservative false-negative
trade.

**Only validate NEW flips.** A bullet that was already `[x]` in the
prior snapshot is not re-validated. Without this, the runner would
churn forever on prior-cycle lies the current agent cannot fix.

**Unfalsifiable bullets don't fire.** "Re-read the verdict" names no
artifact. Treating it as a lie would erode operator trust in the
detector. Falsifiability is the bar.

**Broader path extraction than per-task detectors use.** Per-task
detectors split paths by purpose: `expected_artifacts` for
state/mind/docs synthesis outputs; `intended_code_paths` for
chimera/tests/scripts source files. An INBOX bullet can claim ANY
file as its deliverable, so the INBOX detector unions both.

**Revert the checkbox, not just the log.** The lie has to be undone
in the working tree. Otherwise the next cycle sees a "complete"
checkbox and acts on the lie. The escalation log alone is not
enough — the runner reads INBOX directly.

**Pre-PR submit-pr gate.** v4.97's `chimera submit-pr` verb runs a
branch-level audit before pushing. Add an `inbox_claim_invalid` gate
that scans the worktree's INBOX.md for any `[x]` bullet whose
deliverable is missing. Refuse the PR if any are found — the branch
is shipping a lie.

## Consequences

**Catches Soak v9 Failure C exactly.** The v9 worktree at
`/Users/dave/chimera-soak-v9-2026-05-22-1554` has INBOX.md with five
`[x]` checkboxes, one of which (the regression-test bullet) is a
provable lie. The detector flags exactly one (the others have
deliverables on disk).

**Some risk of false-positives on multi-cycle tasks.** A bullet
written today, completed across multiple cycles, where one cycle
flips the checkbox correctly but the in-cycle write_targets don't
include the final deliverable (because it was written last cycle).
Mitigated by requiring the write_target to include INBOX.md — if
the agent didn't touch INBOX this round, no check runs. The flip
itself is the trigger.

**Trust delta is 1, not 2.** Lying about completion is bad. But
agents will sometimes flip a checkbox optimistically and then
discover the work isn't done. A one-tier demote escalates the
problem (and gives the next attempt opus + remediation hint)
without nuking trust on a single slip. Three lies in short order
still escalate via successive demotes.

## Fixture

- Worktree: `chimera-soak/v9-2026-05-22-1554` at
  `/Users/dave/chimera-soak-v9-2026-05-22-1554`
- `mind/INBOX.md` state after phase 2: five `[x]` checkboxes
- Provable lie: bullet referencing `tests/test_loop_guard.py`; file
  is absent in the worktree
- Other four `[x]` flips: deliverables present on disk; honest

## Code locations

- Detector: `chimera/core/act.py` —
  `check_inbox_claim_validity`, `revert_inbox_lie`,
  `_parse_inbox_tasks`, `_inbox_bullet_artifacts`
- Wiring: `chimera/core/act.py` `_execute_inner` — snapshot at start,
  validate at completion, revert on fire
- Finish-reason registry: `chimera/core/escalation.py` —
  added to `ESCALATING_FINISH_REASONS`
- Trust delta: `chimera/trust/manager.py` —
  `FINISH_REASON_TRUST_DELTAS["inbox_claim_invalid"] = 1`
- Remediation hint: `chimera/core/remediation.py` —
  `_inbox_claim_invalid_hint`
- Submit-pr gate: `chimera/core/submit_pr.py` —
  `_check_inbox_honesty`
- Tests: `tests/test_inbox_claim_invalid.py`
