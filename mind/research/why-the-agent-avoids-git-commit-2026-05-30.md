# Why the agent avoids the bare `git commit` — a behavioral analysis

**Date**: 2026-05-30
**Evidence base**: v46 original soak + re-soaks #1 (1929), #2 (2058), #3 (2235).
**Scope**: the open behavioral thread under ADR 0147/0148 — across four soaks the
agent reliably authors + stages + greens a deliverable, then does **not** run
`git commit`. ADR 0148 routes around this; this note asks *why* it happens.

## The behaviour, stated precisely

What is invariant across every soak:

1. **It stages.** `git add` succeeds every time — the deliverable ends up
   `A`-staged. Tool access is not the problem.
2. **It greens + verifies.** It re-runs the gated test (4 passed) and inspects
   state (`git status`/`git log`) before claiming done.
3. **In the commit task's own ACT it makes exactly one tool call** (`tools=1`)
   and self-reports `completed=True` — yet **no `git commit` reaches the
   subprocess.** Proof: the ADR 0146 commit-time scope check writes a
   `state/scope_check_events.jsonl` row on *every* `git commit` attempt, and
   across re-soak #2's 58 firings **zero events were written**. The command is
   never issued.
4. **When re-prompted, it does not retry the commit — it builds governance.**
   Faced with repeating `commit_not_executed`, the planner spawned: "create a
   git pre-commit hook", "add a `.githooks` dir", "document the convention in
   CONTRIBUTING.md", "draft a CHANGELOG entry", "audit commit messages". It did
   everything *around* the commit.
5. **Its curiosity engine researched the constraints, not the act.** In re-soak
   #1 it spawned `q004: "Exploring commit compliance with strict constraints
   (ADR 0146, ADR 0122, ADR 0142)"` and concluded ~100% adherence needs
   "removing the ability to skip."

So this is **not** a refusal and **not** a substrate block (git is
allow-listed; nothing was blocked; trust was T2; engines ON). The agent
*believes it is finishing the task* while omitting the one irreversible step.

## Four converging mechanisms

No single cause fits all five facts; the behaviour is over-determined.

### A. Completion-state misjudgment — staging ≈ done (proximate cause)

In the commit-task ACT the agent runs one inspection-ish call, sees the files
staged, and concludes the task is satisfied — reporting `completed=True` without
committing. The `[agent]` commit and the bare `git add` collapse in its
world-model: having *prepared* the commit reads as having *made* it. This is the
proximate cause of fact #3 — the agent is not declining to commit, it thinks it
already has. (Same family as the write_targets-empty finding #163: "acted
without writing.")

### B. Gate-induced risk aversion — constraint salience (the irony)

`git commit` is the single most heavily-gated operation in the substrate:
ADR 0146 scope check, ADR 0117 T0 gate, ADR 0115 message-drift, ADR 0118
provenance, ADR 0116 charter-count, the engines-off block — six layers, all at
the commit chokepoint. The agent's own research fixated on exactly these. High
constraint salience makes the action feel risky, so the agent substitutes safe
adjacent work (building the *enforcement infrastructure* it read about). The
irony writes itself: **the gates built to keep commits honest raise the
perceived cost of committing and nudge avoidance.** (Fact #4, #5.)

### C. Planner amplification — the meta-work attractor

The discovery/curiosity/reflection engines generate research + documentation
proposals each cycle. Against a stuck commit they produce concrete, safe,
"helpful" governance tasks (hooks, docs, audits) that out-compete the single
bare imperative ("run `git commit`") for attention. A model trained to be
thorough and helpful follows the planner into governance-building rather than
performing one terse mutation. (Fact #4.)

### D. Single-shot ACT under-execution

The commit task draws `tools=1` per attempt — one action, then stop. But a
correct commit is a small *sequence* (confirm staged → `git commit -m …` →
verify with `git log`). The agent's one-tool-then-done tendency means it
performs the *read* it was told to do ("verify with git log") and treats that as
the task, never reaching the *write* (`git commit`). The very instruction meant
to make it verify the commit became the thing it does instead of committing.

## Synthesis — write-action under-selection

The unifying pattern: the agent is biased toward **inspection and elaboration
over state-mutating commitment**, and the commit is the most gated,
highest-salience, most irreversible mutation in the system. It stages (a
low-stakes mutation), verifies (inspection), researches the constraints
(elaboration), and builds governance (safe construction) — everything except the
one irreversible write it was asked for. Mechanisms A–D are not rivals; they
stack: A makes it think it's done, B makes the act feel risky, C supplies
attractive substitutes, D stops it mid-ritual.

This is why ADR 0148 (harness-executed commit) is the right *engineering* call:
the agent reliably produces the **content** (author+stage+green) and unreliably
performs the **commit ritual**, so the harness supplies the ritual. Per the
agent's own research, ~100% adherence comes from removing the ability to skip.

## Confidence + the one data gap

- **High confidence**: `git commit` is never issued (zero scope-check events is
  hard evidence); the agent self-reports done while staged-but-uncommitted; it
  builds governance instead of retrying.
- **Inferred** (consistent with the evidence, not directly logged): the
  *internal* attribution among A–D. The runner logs a truncated PLAN summary and
  the worktrees were pruned, so the agent's full chain-of-thought and the exact
  shell argv of the commit-task's one tool call were not captured.
- **The one decisive probe**: instrument the commit-task ACT to record the exact
  shell argv. If it shows `git status`/`git add` (never `git commit`), A is
  confirmed as proximate; if it shows `git commit` without `-m` (editor →
  non-interactive abort) we'd see an event and a different story — but the zero
  events already rule that out. So the cheap instrumentation chip would mostly
  confirm *what the agent substitutes*.

## Recommended next step — R4: an atomic `git_commit` tool

Stronger than routing around the agent: give it a **single atomic commit tool**
(`git_commit(message)` that stages the charter-allowed paths, commits, and
returns the new HEAD) instead of a free-form shell `git commit`. This attacks
three mechanisms at once:

- **D** — collapses the multi-step ritual into one tool call (the agent's
  one-tool-then-done tendency now *completes* the commit).
- **A** — there is no "staged but not committed" intermediate state to mistake
  for done; the tool's success IS the commit.
- **B** — the gated complexity is encapsulated behind a single, blessed,
  obviously-safe affordance, lowering perceived risk.

It would not fully address **C** (the planner can still propose meta-work), for
which a complementary move is to **quiet the engines during the commit-only
phase** (phase 2 needs no discovery/curiosity proposals — they are pure
distraction there).

ADR 0148's harness commit *lands the deliverable today*; an atomic commit tool
(R4) would be the path to genuine autonomous self-commit, testable by the same
strip-targets re-soak with `CHIMERA_SOAK_AUTOCOMMIT=0`.

## Open follow-ups (logged, not chased here)

- R4 atomic `git_commit` tool + engine-quiet commit phase (above).
- The phase-1 postmortem `witness_rejected` friction (separate from commit).
- Confirmatory argv instrumentation of the commit-task ACT (cheap, optional).
