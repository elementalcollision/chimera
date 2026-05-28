# v36 micro-soak design — single-item temporal-regression classification

**Date**: 2026-05-28
**Predecessors**:
- [v35 attempt #4 postmortem (PR #112)](https://github.com/elementalcollision/uberagent/pull/112) — operationally PASS, substantively FAIL
- [F2 LoCoMo hybrid-retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — source of the 19 regressed temporal items
- [ADR 0142 §"Temporal-reasoning regression diagnosis"](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) — the v35 chartered question that v36 does NOT re-run
- post-cascade hardening: PRs #103, #105, #106, #107, #108, #109, #110, #113

## Why v36 exists

v35 attempts #1–#4 chartered Chimera to diagnose all 19 LoCoMo F2
temporal-reasoning regressions across three locked hypotheses (H1
retrieval-distractor, H2 context-budget dilution, H3
category-fundamentals) and produce a recommendation (R1/R2/R3).
Every attempt hit `max_rounds=18` on the multi-item classification
task: the autonomous loop never finished one item before the cycle
ended and the planner reset. PR #112 named the structural reason:

> No per-step checkpointing within ACT. The multi-item-classification
> task is not divisible into per-cycle progress under the current
> ACT-phase budget; the agent cannot save partial work.

v36 tests that hypothesis with the smallest converging-or-not
experiment possible.

## Why the atomic unit is ONE item

If the loop cannot converge on classifying a SINGLE regressed
item — read two graded JSONLs, sort, pick the first regressed
item, write one paragraph — then the substrate is more broken
than PR #112 named. If it CAN converge on one item, then a
follow-up chip can fan out incrementally (e.g. 5 items per soak)
with the same scaffolding.

The chip eliminates item-selection discretion: pick the FIRST
regressed item by `item_id` sort order. This removes a foraging
dimension that was almost certainly part of the v35 cycle-cost
explosion.

## Substrate inherited from the v4.116 cascade

v36 is a clone of `scripts/long_cycle_soak_v34.sh`, which has all
post-cascade hardening wired in via `scripts/_soak_common.sh` and
`scripts/soak_lib.sh`:

| Hardening | PR | How v36 inherits |
|---|---|---|
| ADR 0141 secondary-worktree detector | #103 | called inside `soak_run_chimera_with_watchdog` |
| SQLite thread-affinity fix | #105 | `chimera run` invocations from worktree work |
| ACT-phase budget enforcement (240s) | #106 | applies inside every `chimera run` invocation |
| Pre-commit scope check (R1/R2/R3) | #108 | active because chip is R1 — no code edits permitted |
| Forward-progress watchdog | #109 | `soak_check_forward_progress` in `phase_loop` |
| Task-completion watchdog | #113 | `soak_check_task_completion` in `phase_loop` |

No modification of any cascade-hardening surface. The scaffold is
held constant; only the INBOX charter and the deliverable filename
change.

## The three locked outcomes

After the soak runs, classify the result into exactly ONE of three
bands. No fourth band.

### CONVERGES

- The research note `mind/research/v36-locomo-temporal-one-item-classification.md` exists
- It ends with `## READY-FOR-REMEDIATION` and contains "R1 — no code change."
- It names exactly ONE `item_id` and ONE hypothesis label (H1/H2/H3/H4)
- It contains a classification paragraph (≤ 6 sentences)
- Phase 2 produced a clean commit on the soak branch via the pre-commit scope check
- No other files modified

**Interpretation**: PR #112's structural hypothesis is **partially
falsified**. The loop CAN converge on a sufficiently atomic task.
**Follow-up**: charter a v37 chip that fans out to 5 items per soak,
preserving the sort-first item-selection rule.

### STALLS

- Forward-progress watchdog OR task-completion watchdog fires
- Phase 1 or phase 2 aborts before the research note ships
- No commit lands on the soak branch

**Interpretation**: PR #112's structural hypothesis is
**strengthened**. Even ONE atomic item is beyond what the substrate
can complete autonomously. **Follow-up**: pause autonomous-loop work
on temporal-regression diagnosis; move to non-soak human-driven
analysis (operator drives the classification, agent contributes
narrow lookups via the Read tool).

### CONFABULATES

Either:
- The pre-commit scope check refuses the commit because the diff
  includes code changes beyond the research note, OR
- The classification paragraph cites numbers, item_ids, hypothesis
  texts, or session counts that don't appear in the F2 graded
  JSONL or the F2 postmortem note

**Interpretation**: the substrate produces work but can't be trusted
to stay within scope or cite real data. The scope check + the
operator catch it before it ships. **Follow-up**: this is a
substrate-quality signal — strengthen the pre-commit scope check
and/or add a data-citation lint before chartering more soaks.

## Pre-launch sanity checklist

Operator runs before invoking the soak:

1. **Watchdog wiring**: confirm `scripts/long_cycle_soak_v36.sh`
   contains both `soak_check_forward_progress` and
   `soak_check_task_completion` calls inside `phase_loop` (lines
   should match v34 verbatim modulo the comment about PR #113).
2. **Data sources exist**:
   - `ls /tmp/locomo-f1/hypotheses.graded.jsonl` → 1,986 lines
   - `ls /tmp/chimera-f2-locomo-v6/results.graded.jsonl` → 1,986 lines
3. **Bash syntax**: `bash -n scripts/long_cycle_soak_v36.sh` clean
4. **Tests still green**: `uv run pytest -q` (no behavior changes
   in this chip — the runner is bash, tests should pass identically
   to main)
5. **Chip's PR is merged to main** before launching the soak — the
   soak clones the worktree from main and expects the v36 runner
   to be present.

## Comparison to v35

| Dimension | v35 (attempts #1–#4) | v36 |
|---|---|---|
| Items classified | all 19 | 1 (first by sort) |
| Hypothesis space | H1/H2/H3 + R1/R2/R3 recommendation | H1/H2/H3/H4 label only |
| Item-selection discretion | yes (agent picks order) | no (sort-first, locked) |
| Deliverable | research note + ADR 0142 amendment + recommendation | research note only |
| Scope check phase | R2 (substantive amendment to ADR) | R1 (no code change) |
| Post-cascade hardening | retrofitted across 4 attempts | inherited by cloning v34 |
| What it tests | the substantive temporal-regression diagnosis | the substrate's ability to converge on ONE atomic task |

v35's chartered question (the actual diagnosis) is paused per PR #112.
v36 is upstream of it: until we know the loop can converge on ONE
item, the multi-item question is unanswerable by this substrate.

## Operator launch and supervisor

This chip lands the v36 runner; it does NOT launch the soak.
Operator owns the launch. A separate supervisor chip — same shape
as the v35 attempt #4 supervisor — will be chartered after the v36
runner merges, to watch the run and classify the outcome into
CONVERGES / STALLS / CONFABULATES.
