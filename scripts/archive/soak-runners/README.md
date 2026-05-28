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
