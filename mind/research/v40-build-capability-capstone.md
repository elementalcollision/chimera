# v40 build-capability — capstone (4 attempts; the experiment answered the question)

**Date**: 2026-05-29
**Charter**: `mind/research/v40-build-mind-count-design.md` (PR #135) — first
R3 build soak: can Chimera's ACT phase author code that lands in main?
**Attempts**: 4 (postmortems: attempt1, attempt2, attempt3, this capstone covers #4)
**Total spend across all 4**: ~$1.57. **Outcome**: the five-gate clean
convergence was **not achieved**; per the locked rule, **the ladder stops** —
but the experiment produced a rich, defensible answer to "what happens when
we ask Chimera to build?"

## The four attempts

| # | build correct? | ran the test (ledger)? | committed? | proximate blocker | whose bug |
|---|---|---|---|---|---|
| 1 | **YES** (blind) | no — harness blocked | no | env-prefix command form + system `python3` | mine |
| 2 | NO (summary line) + `os`-shadow | no | no | INBOX fragmented into independent tasks | mine + agent |
| 3 | **YES** | ran, not recorded | no | `is_test_command` blind to `uv run pytest` | mine |
| 4 | **YES** | **YES — recorded `passed:true`** | no | `Path`-shadow inside `main()` bricks `chimera run` → `no_forward_progress` | agent |

## What is now PROVEN

1. **Chimera authors correct narrow code.** 3 of 4 attempts produced a
   `chimera mind count` that passes the pre-written 5-test contract
   (operator-verified each time; attempt #4 even produces correct
   per-entry output live: `research_scenario_transcript.md: 1`, `soak: 2`,
   `wiki: 6`). It correctly inferred argparse registration, `mind_dir`
   resolution via `LoopConfig.from_env()`, recursive `os.walk`, hidden
   skipping, and alpha sort — from reading the test contract alone.
2. **It runs its own tests, and the instrumentation now records them.**
   Attempt #4's test-run ledger has a `passed:true` row from the agent's
   `uv run --extra dev pytest` invocation — the verdict-honesty gate is
   finally functional ( `jq -s 'any(.[]; .passed==true)'` → true ).
3. **Its self-reporting is honest.** Across all four it never fabricated
   success: under-claimed (#1), reported accurate FAILED (#2), and
   self-diagnosed a substrate instrumentation bug (#3, "the test-run
   ledger was not written by the substrate").

## What BLOCKED a clean convergence

Two separable causes — and only the first is Chimera's:

### A recurring agent code-quality defect: function-local import shadowing

In #2 and #4 the agent added a function-local import inside `main()`
(`import os` in #2, a `Path` reference shadowed by a local import in #4).
Python then treats that name as local for the WHOLE function, so an
earlier reference in `main()` raises `UnboundLocalError`. This **bricks
`chimera run`** — and the narrow per-feature test (`mind count` only)
cannot see it. It is a genuine R3 build-quality blind spot: the agent
does not recognize that a local import inside a large function shadows
the module global across the entire scope.

### A charter-design flaw (mine): the target lived in the loop driver

v40 chose `chimera/cli.py` as the build target — but `cli.py` defines
`main()`, which **is** `chimera run`, the loop driver the soak uses to
drive the agent. So when the agent's edit regresses `main()`, it bricks
its own driver: cycle freezes, spend freezes, the forward-progress
watchdog kills the soak (attempt #4: stalled at $0.078, cycle 146, both
phases `no_forward_progress`). The agent's code-quality defect is real,
but the soak architecture **amplified it into a self-denial** that a
better-isolated target would have survived (the loop would keep running,
the witness/iterate cycle could catch and fix the regression).

### The harness cascade (mine; all fixed)

Three distinct harness/instrumentation bugs, one per attempt, each fixed
and re-run (PRs #141, #142, #143): env-prefix command form, system-python
interpreter, INBOX task fragmentation, and `is_test_command` ledger
detection. The conservative N=1 rung surfaced all of them for ~$1.57
before any fan-out — exactly its purpose. By attempt #4 the harness was
defect-free on all known fronts, which is how #4 cleanly isolated the
*agent's* shadow defect as the remaining blocker.

## Verdict

**v40 did not clear the five-gate in four attempts; the ladder stops here**
(locked rule). But "Chimera cannot build" is the wrong reading. The honest
finding: **Chimera reliably authors correct narrow code and runs/reports on
it honestly, but (a) has a code-quality blind spot around function-local
import shadowing, and (b) the v40 charter put the build target inside the
loop driver, turning that blind spot into a fatal self-denial.** No clean
end-to-end commit was ever observed — not for lack of build skill, but
because the loop kept dying before commit, on a different cause each time.

## Recommendation (operator decision — do NOT auto-retry v40 as-is)

A 5th identical attempt is not warranted; the blockers are now understood
and structural. Options, in priority order:

1. **Re-charter as v40′ with an isolated target.** Point the build at a
   NEW standalone module (e.g. `chimera/mindcount.py` + a thin one-line
   hook), NOT `chimera/cli.py`. A regression there cannot brick `chimera
   run`, so the loop survives, the witness/iterate cycle can self-correct,
   and a clean commit becomes reachable. This directly tests build
   capability without the self-denial confound. **Recommended.**
2. **Broaden the gate with a `chimera run` smoke check** so import-shadow
   regressions are caught by the test the agent must pass — turning the
   blind spot into a red test it can iterate against.
3. **R2 detector chip**: a lint/AST check for function-local imports that
   shadow module-level names, wired into the ACT gate sequence (sibling to
   the existing scope/scope_evasion/fix_without_test detectors).

(1) + (3) together would both unblock the build-capability question and
harden the substrate against the class of defect the experiment found.
The v41+ fan-out stays on hold until v40′ achieves one clean convergence.

## Artifacts

All four worktrees retained for review:
`~/chimera-soak-v40-2026-05-29-{1509,1535,1556,1630}`. Ledgers under each
worktree's `mind/soak/<run-id>/`. Per-attempt postmortems:
`v40-attempt{1,2,3}-postmortem.md` + this capstone.
