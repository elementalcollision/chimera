# Scope-check design-note matching — v36-postmortem follow-up C

**Date**: 2026-05-28
**Author**: Chimera agent (spawned task)
**Status**: implemented in `fix/scope-check-design-note-prefix`
**ADR touched**: 0146 (§Consequences amendment, status unchanged)
**Closes**: v36 micro-soak postmortem follow-up C (PR #117)

## Context

PR #117 (`docs: v36 micro-soak postmortem — CONVERGES`, merged at
99424b8) documented a subtle defect in `find_active_design_note` in
`chimera/core/scope_check.py`. The current implementation selects the
"latest `*-design.md` by mtime" — which during the v36 soak picked the
wrong note.

Verbatim quote from the v36 postmortem (PR #117):

> **Anomaly**: the matched design note was
> `v34-preference-dialectic-design.md`, not the v36 design note, and
> the recommendation's `allowed_paths` (`dialectic.py`, ADR 0137, etc.)
> had no overlap with the staged path. The commit was allowed because
> research notes under `mind/research/*` are auto-allowed by the v4
> journal-auto-allow rule independent of the recommendation. The
> guard's *outcome* was correct (allow the research-note commit), but
> the *reasoning trace* matched the wrong design note.

The guard's *outcome* was correct, but only by accident — the
`mind/research/*` auto-allow rule covered for the wrong reasoning
trace. If the staged path had been outside `mind/research/`, the
mismatched recommendation could have either falsely refused a
legitimate commit (worse) or — combined with an adversarially-named
note — falsely allowed an off-charter commit (worst).

## Options considered

### Option A — filename-prefix match against branch name (PICKED)

Read the current git branch via `git rev-parse --abbrev-ref HEAD`. If
it matches `<host>/<rest>` (e.g. `chimera-soak/v36-2026-05-28-1537`),
extract the leading alnum token of `<rest>` (`v36`) and prefer
`mind/research/<prefix>-*-design.md`. Fall back to the legacy mtime
heuristic on any failure (detached HEAD, branch without `/`,
unparseable, no match).

- **Pro**: principled (branch is the source of truth for chip identity
  in this repo's workflow); no new config; pure local change to one
  function; backward compatible (main branch / manual commits behave
  identically); cheap (one `git rev-parse` per check).
- **Con**: heuristic on branch naming convention (`<host>/<chip>-…`);
  doesn't help when an operator branches off-convention. Mitigated by
  preserving the mtime fallback as defense-in-depth.

### Option B — explicit charter pointer

Add a `.chimera-active-chip` file (or pyproject field) that names the
active design note explicitly. Engine writes it when a chip is
chartered.

- **Pro**: removes all heuristics; fully principled.
- **Con**: new state file, new engine wiring, new failure mode (stale
  pointer), and out of scope of the locked ≤4-file fix. Worth
  considering later if Option A ever picks the wrong note.

### Option C — content-based recency

Parse each note's front-matter for a chartered-at timestamp and pick
the most recently chartered. Postmortems append RESOLVED/CONVERGES
sections, so this could also weight against closed notes.

- **Pro**: no dependence on branch convention; survives operator
  off-convention branches.
- **Con**: requires structured front-matter we don't currently enforce;
  parsing-by-heading is brittle in the exact way that bit us at v35.
  Reintroduces the same class of problem.

## Picked: Option A

Branch name carries chip identity in this repo's workflow — every
soak runner, every chip-chartered branch is shaped
`<host>/<chip>-<date>-<seq>`. Matching that prefix against design-note
filenames is principled given the convention, and the mtime fallback
preserves all non-soak behavior.

Honest disclosure: the fix makes the heuristic *principled*, not
*bulletproof*. An operator who branches off-convention (e.g. plain
`fix/v37-something` while v36 notes still exist) could still hit the
mtime fallback and select an older note. The `mind/research/*`
auto-allow rule is preserved as defense-in-depth for exactly this
case — a wrong-reasoning-trace outcome is still bounded to research
notes, never code paths.

## Test coverage matrix

| # | Test | Branch state | Notes | Expected pick |
|---|------|--------------|-------|---------------|
| 1 | `matches_branch_prefix` | `chimera-soak/v36-…` | v34 newer mtime, v36 older | **v36** (prefix wins over mtime) |
| 2 | `falls_back_to_mtime_when_no_prefix_match` | `main` | a, b notes | **b** (mtime fallback preserved) |
| 3 | `detached_head_falls_back` | detached HEAD | a, b notes | **b** (mtime fallback; no raise) |
| 4 | `branch_without_slash_falls_back` | `feature-foo` | a, b notes | **b** (mtime fallback; no raise) |
| 5 | `no_design_notes_returns_none` | `chimera-soak/v99-…` | empty research dir | **None** |

Existing tests `find_active_design_note_returns_latest` and
`find_active_design_note_none_when_dir_missing` continue to pass — the
former runs on `main` (init default) so the mtime fallback still
applies.

## What changes / what doesn't

- **Changes**: `find_active_design_note` consults git branch first.
- **Doesn't change**: `evaluate_commit_scope`, `check_commit_scope`,
  classifier, parser, override env, event logging, ADR 0146 status,
  `mind/research/*` auto-allow rule.
- **No new env knobs**.
- **Backward compatible**: main branch, manual commits, detached
  checkouts, and off-convention branches all hit the legacy mtime
  fallback exactly as before.

## READY-FOR-REMEDIATION

R1 — no code change beyond this commit (the implementation itself
satisfies the recommendation). Reopen with a fresh chip only if a
future soak demonstrates Option A picking the wrong note.
