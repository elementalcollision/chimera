# Soak runner consolidation (v25–v34)

**Date**: 2026-05-27
**Scope**: Pure housekeeping. `scripts/long_cycle_soak_v25.sh` …
`scripts/long_cycle_soak_v34.sh` (10 runners, 5,087 lines combined).
**Outcome picked**: **#3 — archive everything but the latest (v34)**.

## Inventory

| Version | Lines | Chip / charter                                                                 | Status   |
|---------|------:|--------------------------------------------------------------------------------|----------|
| v25     |  563  | v4.116 sub-soak A: `ActResult.charter_file_count_violations` field             | archived |
| v26     |  462  | v4.116 sub-soak B: `check_charter_file_count` call site in `act.py`            | archived |
| v27     |  462  | v4.116 sub-soak C: add to `ESCALATING_FINISH_REASONS`                          | archived |
| v28     |  464  | v4.116 sub-soak D: add to `FINISH_REASON_TRUST_DELTAS`                         | archived |
| v29     |  462  | v4.116 sub-soak E: `_charter_file_count_hint` in `remediation.py`              | archived |
| v30     |  451  | v4.116 coverage hardening (single-file e2e test)                               | archived |
| v31     |  444  | chip-branch-jump detector layer 1/3 (silent-death incident)                    | archived |
| v32     |  453  | Chip T1.1: `max_tokens` 512→2048 + `--answer-max-tokens` flag                  | archived |
| v33     |  488  | Chip T1.2: cross-session dialectic prompt (ADR 0136)                           | archived |
| v34     |  507  | Chip T1.3: preference-honoring dialectic prompt (ADR 0137)                     | **kept** |

Helpers (`scripts/_soak_common.sh`, 141 lines; `scripts/soak_lib.sh`,
190 lines) were out of scope and remain untouched except for one
internal-comment update (see below).

## Diff-matrix summary

Each `vN → v(N+1)` diff was confined to:

1. Identifier substitutions: `BRANCH`, `WORKTREE`, `LOG`,
   `soak_refuse_concurrent` argument, `log` banner.
2. **Phase-1 INBOX charter text** — the chip-specific instruction
   block (10–80 lines per version, all rewritten per chip).
3. Two structural milestones in the otherwise-identical scaffolding:
   - **v30**: shifted charter shape from source-modifying sub-soaks
     to single-file test-only deliverables.
   - **v32**: added a `soak_sync_main_from_origin` step (fix for
     PRs #61/#62 where the worktree forked from stale local main).
     v33 and v34 preserve this step.

No version introduced an option flag or env var that a later version
removed. The Phase-1 INBOX is the only meaningful axis of variation;
the orchestration scaffolding is otherwise a single template that
has been hand-propagated across copies.

## Consolidation decision and rationale

**Outcome #3** is correct because:

- The orchestration scaffolding in v34 is the latest-and-most-complete
  shell (includes the v32 origin-sync fix; nothing structural was
  added or removed in v33→v34).
- Earlier runners' uniqueness is **charter text for chips that have
  already shipped**. That text is historical context, not load-bearing
  infrastructure.
- Outcome #1 (a single canonical parameterised runner) would require
  externalising the INBOX charter — that is a *behaviour change*
  forbidden by this chip's discipline gates. Future chips can move in
  that direction if it proves useful; this chip just removes the
  duplicate-script smell.
- Outcome #2 (two-runner pair) does not apply — there is no second
  harness shape in scope; all 10 runners are variants of the same
  single-soak shape.

## Migration map

| Old reference                                   | New target                                                      |
|-------------------------------------------------|-----------------------------------------------------------------|
| `scripts/long_cycle_soak_v25.sh`…`v33.sh`       | `scripts/archive/soak-runners/long_cycle_soak_v{25..33}.sh`     |
| `_soak_common.sh` line 27 pgrep-example comment | rewritten to reference `long_cycle_soak_v34.sh`                 |
| `_soak_common.sh` lines 30–31 (v31 postmortem)  | unchanged — these point at the v31 *incident*, not the script   |
| `mind/research/v31-silent-death-postmortem-…md` | annotated with a footer pointing readers to the archive path    |

## Line-count delta

- Before: `scripts/long_cycle_soak_v*.sh` = **5,087 lines** across 10 files.
- After: `scripts/long_cycle_soak_v*.sh` = **507 lines** in 1 file (v34).
- Active-surface delta: **−4,580 lines**.
- Archive: 4,580 lines preserved at `scripts/archive/soak-runners/`.
- Total repo line count is approximately conserved (file moves, no deletions).

## Smoke verification

The runners are long-cycle harnesses that cannot meaningfully be
unit-tested in CI. Operator-side smoke is the verification layer.
Suggested smoke command for the surviving v34 runner:

```bash
# Dry parse only (do NOT execute a real soak in CI):
bash -n scripts/long_cycle_soak_v34.sh
```

A real-execution smoke (operator workstation only) would be:

```bash
# Fresh shell with provider keys sourced:
./scripts/long_cycle_soak_v34.sh
```

This will branch off a `chimera-soak/v34-$STAMP` worktree, run the
Chip T1.3 charter, and log to `state/long_cycle_v34_*.log`. No
behaviour change vs prior to this PR.

## Honest disclosures

- The "load-bearing vs purely historical" judgement is subjective.
  We defaulted to over-preservation — all 9 earlier runners are
  archived rather than deleted, and the archive directory carries
  a README with a per-version chip summary.
- No option flags were removed; v34's flag surface is the union of
  all flags that ever existed (the scaffolding never lost any).
- Flag-removal, if ever desired, is a separate decision from this
  consolidation and would require its own chip.
- The future-template authoring convention "copy v34 → v35 and
  rewrite the INBOX block" is preserved verbatim from the
  prior-art comment block in v34 itself.

## Follow-up chips (not done here)

- *None mandatory.* If a future operator finds the copy-and-modify
  cycle still painful, a follow-up could externalise the INBOX
  charter into a separate `mind/charters/v35-*.md` file and add
  a `--charter <path>` flag to the runner. That would be Outcome
  #1 from this chip's spec, but is a behaviour change and out of
  scope for pure cleanup.
