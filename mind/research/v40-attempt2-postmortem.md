# v40 build-capability soak — attempt #2 postmortem (FAILED; charter-structure root cause)

**Date**: 2026-05-29
**Soak**: `chimera-soak/v40-build-mind-count-2026-05-29-1535` (worktree retained)
**Charter type**: R3 build — `mind/research/v40-build-mind-count-design.md`
**Run id**: `v40-build-mind-count-2026-05-29-1535`
**Spend**: $0.19 / $3.00. **Trust**: T5→T2 (worktree-local). No commit, no auto-push.
**Outcome**: **FAILED** — incorrect implementation, loop never converged.

## What happened

With the attempt-#1 harness defects fixed (PR #141: `uv run --extra dev pytest`,
no env prefix), the agent could now run the gated test. It did not.

Phase-1 exit reason: **`no_task_completion last_k=0 iters=8`** — the
task-completion watchdog killed phase 1; the soft-sentinel never fired
(test never went green). Phase 2 then crashed every iteration (see below).

ACT narrative (6 cycles, finish reasons from `act-tools.jsonl`):

| cycle | task (from the 6-checkbox INBOX) | finish | result |
|---|---|---|---|
| 146 | read test | stop | ✓ |
| 146 | read cli.py | stop | ✓ |
| 146 | implement mind subparser | **scope_evasion** | demote ×2 |
| 146 | "run the test and iterate" | **stop / completed=True** | **but never ran it** |
| 146 | write postmortem | **artifact_missing** | — |
| 147 | implement (retry) | **witness_rejected** (15 rounds, 21 tools) | budget exceeded |

**`test-runs.jsonl` is empty** — the agent never executed the gated test,
in any cycle.

## Root cause: the INBOX fragmented into independent tasks

The phase-1 INBOX was a **6-checkbox list**. The loop parses each `- [ ]`
into a SEPARATE ACT task. So **"Run the test and iterate until 5 pass"
became its own task, decoupled from "implement."** The agent marked that
task `completed=True` with a `stop` **without running anything** — there
was no forcing function tying test-execution to the implementation, and a
standalone "run the test" task has no artifact to verify against.

This is why the test was never a real gate on the code in EITHER attempt:
- attempt #1: the decoupled "run test" task trivially "passed" because the
  harness blocked execution anyway (my bug);
- attempt #2: the decoupled "run test" task trivially "passed" by the agent
  declaring it done.

The narrow gate also can't catch what it doesn't cover (see below).

## Two substantive code defects (Chimera's, this time)

1. **Wrong output format.** The agent printed a single summary line —
   `mind count: N files, M dirs under <dir>` — instead of the contract's
   one `<name>: <count>` line per top-level entry (sorted, recursive,
   hidden-skipping). It did not implement the actual contract. (Operator
   re-ran the test against the agent's code: `5 failed`.)
2. **`import os` shadow regression.** The agent put `import os` INSIDE the
   `mind` branch of `main()`, making `os` a local for the whole function
   and breaking the `run` command at the unrelated branch-drift check
   (`UnboundLocalError`, cli.py:1936). The pre-written test only covers
   `mind count`, so this regression to `chimera run` is invisible to the
   gate — and phase 2 drives commits via `chimera run`, so it crash-looped.

## Two-attempt synthesis

Across #1 (correct code, built blind, harness blocked verification) and #2
(wrong code, never tested, didn't converge), Chimera has **not once cleanly
closed the build loop** (write → run test → see red → iterate → green →
commit). #1's correctness was a blind one-shot; #2, with feedback available,
didn't use it. The dominant blocker is **charter structure**, not raw
capability: the build and its verification were never a single unit.

## Fix (attempt #3, this chip)

`scripts/long_cycle_soak_v40.sh`:
1. **Collapse the INBOX to two cohesive tasks.** Task 1 bundles
   read+implement+run-test+iterate with test-execution INTRINSIC and an
   explicit completion gate: "NOT done until you have run the command and
   its output shows `5 passed`." Task 2 is the postmortem (only after green).
2. **Raise the ACT budget** `CHIMERA_ACT_BUDGET_SECONDS=600` so the cohesive
   build→test→iterate task has room (attempt #2 hit the 240s budget at
   rounds 12–15 before one cycle could close).
3. **Targeted defect hints**: the exact `<name>: <count>` per-entry contract
   ("not a summary line"), and "do NOT `import os` inside any function —
   use the module-level import."

Relaunch attempt #3 from a fresh worktree. If it still fails to close the
loop, the honest finding stands: capable of authoring code, but not yet
autonomously reliable at closing a verified R3 build loop — and the next
move is an R2 charter on the substrate gap (agent does not run its own tests).
