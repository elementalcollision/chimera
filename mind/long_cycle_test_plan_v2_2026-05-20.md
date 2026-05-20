# Long-cycle test v2 — Interventional (2026-05-20 evening)

**Operator brief.** Second multi-hour soak test, **interventional** this
time. The agent investigates a real bug surfaced by run #1 and
prototypes a fix in a sandboxed git worktree.

## Differences from run #1

| | Run #1 (observational) | Run #2 (interventional) |
|---|---|---|
| Goal | Research + write artifacts | Investigate + fix a real bug |
| Edit scope | mind/ + state/ only | Sandboxed git worktree with chimera/* editable |
| Budget | $10 single | $10 research + $10 remediation (separate watchdogs) |
| Outcome | Findings | A branch with code changes the operator can review |

## The target

The 2026-05-20 long-cycle test surfaced one **hot signature**:

```
×2  tiers=haiku/sonnet        cycles=41→42  last=degenerate_loop_abort
    "Create a glossary of all capability terms used in the matrix as
     a standalone markdown file in mind/research"
```

ACT's `detect_degenerate_loop` (in `chimera/tools/loop_guard.py`) fired
twice on what was, to the operator, a perfectly reasonable subtask:
generate a glossary file from a matrix. The task aborted at round 6
both times — once on haiku, once on sonnet.

**Falsifiable questions for the agent to answer:**

1. **Why** did the loop guard fire on this task? Specific: which tool
   was being repeated, at what rounds, with what arguments?
2. Is the loop guard's verdict **correct** (the agent really was
   stuck in a degenerate pattern) or a **false positive** (the
   pattern is actually progressive but looks degenerate by the
   guard's heuristic)?
3. If false positive: what's the minimum change to `loop_guard.py`
   that admits this pattern as progressive while still catching
   the degenerate cases the guard was built for?
4. If correct: what's the right ACT-loop behaviour when a glossary-
   style task hits the guard? Re-prompt? Escalate tier? Decompose?

## Phased budget

```text
Phase 1: research / investigation   cap $10  watchdog A
   ↓ agent declares READY by writing mind/research/loop-abort-investigation.md
   ↓ with "## READY-FOR-REMEDIATION" as a section header
Phase 2: remediation / prototype    cap $10  watchdog B
   ↓ agent edits chimera/tools/loop_guard.py (and tests/)
   ↓ commits to chimera-soak/<timestamp> branch
   ↓ runs `uv run pytest tests/test_loop_guard.py` and reports
```

The runner watches `mind/research/loop-abort-investigation.md` for the
`## READY-FOR-REMEDIATION` marker. Once present (or $9.50 of research
budget spent, whichever first), phase 1 ends and phase 2 starts.

## Sandbox guarantees

- **Git worktree:** `git worktree add ../chimera-soak/2026-05-20`
  creates a parallel checkout on branch `chimera-soak/2026-05-20`.
  All editing happens there.
- **No push capability:** `git remote remove origin` inside the
  worktree before the run starts. Agent literally cannot push.
- **Isolated state:** `CHIMERA_STATE_DIR=<worktree>/state` —
  a fresh DB. Run #1's escalation/scoring/proposer-status history
  doesn't pollute this run, and vice versa.
- **Read-only mind seed:** `mind/` content from main is symlinked
  (CHRONICLE, INBOX subset, the run-#1 research files for context)
  but writes go to a per-run mind/ in the worktree.
- **Cost discipline:** All four caps from run #1 stay (per-cycle,
  per-task, rolling-60m), plus the two new watchdogs.

## Why this target

- It's **falsifiable** — there are concrete outcomes (the loop
  guard's heuristic is one specific function, the test fixture is
  reproducible from `task_escalations`).
- It exercises the **skill-assembler ladder under load** — fixing
  loop_guard.py is a non-trivial code change, the witness ladder
  will be exercised.
- It exercises **v4.74's session-relative engine mode** — the
  runner sets `CHIMERA_ENGINE_SESSION_MODE=1` so we get real data
  on whether session-mode produces healthier engine firings than
  the UTC-window mode did in run #1.
- It exercises the **v4.73 proposer-scoring backfill** — if any
  proposer is already degraded at session start, we'll see it.
- The **degenerate_loop_abort** itself, if real, blocks similar
  future tasks. Fixing it pays back the budget directly.

## Acceptance criteria

The run is **successful** if at the end:

1. `mind/research/loop-abort-investigation.md` exists with a
   reproducible explanation of why the guard fired (rounds,
   tool sequence, args).
2. A judgment is recorded: false positive OR correct verdict.
3. **If false positive:** a minimal patch to `loop_guard.py` is
   committed to the soak branch, with a test that captures the
   reproducing case and asserts the new behaviour.
4. **If correct:** an ADR-shaped doc at
   `mind/research/loop-abort-remediation.md` describes the design
   change for ACT (re-prompt, decompose, escalate) and a prototype
   patch implementing the simplest option.
5. `uv run pytest tests/test_loop_guard.py` passes on the branch.
6. Total spend ≤ $20.

The run is **a useful failure** if (1) and (2) exist but no patch
landed — tells us the analysis layer scales but the implementation
layer needs more scaffolding.

## After the run — operator review checklist

```bash
cd ../chimera-soak/2026-05-20
git log --oneline main..HEAD              # what the agent committed
git diff main -- chimera/                 # what changed in core
git diff main -- tests/                   # new/changed tests
cat mind/research/loop-abort-investigation.md
cat mind/research/loop-abort-remediation.md 2>/dev/null
uv run pytest -q                          # full suite on the soak branch

cd -                                       # back to main
tail -120 state/long_cycle_v2_*.log
```

If the diff is good: `git merge chimera-soak/2026-05-20` (or
cherry-pick specific commits). If not: `git worktree remove
../chimera-soak/2026-05-20` and `git branch -D chimera-soak/2026-05-20`.

## How to launch

```bash
bash scripts/long_cycle_remediation.sh
```

Live tail: `tail -f state/long_cycle_v2_2026-05-20.log`. SIGINT
behaviour same as run #1 — finishes the current cycle, exits cleanly.
