# Archived soak runners (v25–v33)

These are historical incarnations of `scripts/long_cycle_soak_v*.sh`,
archived on 2026-05-27 as part of the v25–v34 consolidation chip.

Each runner shares the same orchestration scaffolding (sourced from
`scripts/_soak_common.sh` and `scripts/soak_lib.sh`); the differences are
chip-specific charter text embedded in the Phase-1 INBOX section, plus
version-string substitutions in branch/log/worktree paths. The latest
scaffolding is preserved live in `scripts/long_cycle_soak_v34.sh` — when
a new soak is needed, copy that file to the next version number and
replace the INBOX block.

`scripts/long_cycle_soak_v36.sh` is the post-cascade clean restart:
the first micro-soak after the v4.116 hardening cascade, charter
shape "research-note + commit" (single-file deliverable, R1), used
to test whether the autonomous loop can converge on a single atomic
classification task. v35's chartered question is paused per
[PR #112](https://github.com/elementalcollision/uberagent/pull/112);
v36 is upstream of it.

`scripts/long_cycle_soak_v37.sh` is the N=5 fan-out follow-up to
v36's CONVERGES result (PR #115 / postmortem PR #117). Same R1
research-note-and-commit shape, same H1/H2/H3/H4 hypothesis space,
same sort-first item-selection rule — but classifies the first FIVE
LoCoMo F2 temporal-reasoning regression items instead of one.
Item #1 (`conv-26::qa14`) is the same item v36 hit, giving a
built-in per-run consistency check. Adds a fourth locked outcome
band (PARTIAL) for the fan-out-specific failure mode where the loop
classifies some but not all five items. Inherits PR #118's phase-1
soft-sentinel and PR #119's branch-prefix design-note selection.

## Inventory

| Version | Lines | Chip / charter                                                                            |
|---------|-------|-------------------------------------------------------------------------------------------|
| v25     | 563   | v4.116 sub-soak A: add `charter_file_count_violations` field to `ActResult`               |
| v26     | 462   | v4.116 sub-soak B: add `check_charter_file_count` call site in `act.py`                   |
| v27     | 462   | v4.116 sub-soak C: add `charter_file_count` to `ESCALATING_FINISH_REASONS`                |
| v28     | 464   | v4.116 sub-soak D: add `charter_file_count: -1` to `FINISH_REASON_TRUST_DELTAS`           |
| v29     | 462   | v4.116 sub-soak E: add `_charter_file_count_hint` to `remediation.py`                     |
| v30     | 451   | v4.116 coverage hardening: end-to-end regression test for the 5 wired layers              |
| v31     | 444   | chip-branch-jump detector layer 1/3 — see `mind/research/v31-silent-death-postmortem-…md` |
| v32     | 453   | Chip T1.1: `max_tokens` 512→2048 + `--answer-max-tokens` CLI flag                         |
| v33     | 488   | Chip T1.2: extend `_DIALECTIC_PROMPT` with cross-session instructions (ADR 0136)          |

## Known false claim in archived INBOX prose

Every archived runner here (v25–v33) — and v34/v35 prior to the
ladder-#5 fix — contains this Phase-2 INBOX line:

> The wiring_coordinator handles push + PR + merge on a
> successful soft-sentinel exit.

**This claim is false.** None of these runners invoke
`scripts/wiring_coordinator.sh`; after a soft-sentinel deliverable
lands, the runner simply breaks out of `phase_loop` and exits,
leaving the branch in the worktree for manual operator review. The
archived files are preserved as-is for git-history accuracy per the
v25–v34 consolidation policy, but **do not copy this prose forward
when templating a new runner** — use the corrected wording in
`scripts/long_cycle_soak_v34.sh` / `long_cycle_soak_v35.sh`
("NO auto-push, NO auto-PR, NO auto-merge") instead. See PR closing
v35-postmortem ladder #5 for the full diagnosis.

## Scaffolding milestones

- **v25** introduced the focused-remediation runner shape (long-form
  INBOX, 2-phase structure, $5+$5 budget caps).
- **v30** flipped charter shape to single-file-deliverable (test-only)
  for v4.116 coverage hardening.
- **v32** added the `soak_sync_main_from_origin` step (post-mortem fix
  for PR #61/#62 where the worktree forked from a stale local main).
  v33 and v34 preserve this step.

If you need to reproduce a historical run, note that the archived
runners source helpers via `$(dirname "$0")/_soak_common.sh` and
`$(dirname "$0")/soak_lib.sh` — relative to the script's own
directory. From the archive path those resolve to non-existent files,
so to execute an archived runner either:

1. Copy it back to `scripts/` temporarily, or
2. Patch the two `source` lines to point at `../../<helper>.sh`, or
3. Check out the pre-consolidation commit (last tag before this PR).
