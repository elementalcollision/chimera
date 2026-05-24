# Wiring decomposition methodology

**Status**: Proposed
**Date**: 2026-05-24
**Author**: operator (after v22/v23/v24 retrospective)
**Companion ADRs**: 0114 (autonomous-delivery contract), 0117/0119 (load-bearing chain)

## Problem

The autonomous-delivery contract (ADR 0114) defines a "shippable PR with
zero operator code patches." It has shipped 4 times under the strict bar
established by the load-bearing chain (v4.115/117/118/119):

| Soak | Target | Shape | Files | Result |
|---|---|---|---|---|
| v17 | `_check_orphan_worktrees` | add-one-function | 2 | ✅ ship |
| v18 | `prune_escalations` | add-one-function | 2 | ✅ ship |
| v19 | `chimera escalations prune` CLI verb | wiring (2-file) | 2 | ✅ ship |
| v21 | `_check_uv_installed` | add-one-function | 2 | ✅ ship |

It has **failed** 3 times on a single multi-file wiring target:

| Soak | Target | Shape | Files | Result |
|---|---|---|---|---|
| v22 | `check_charter_file_count` wiring | multi-module (5-file) | 5 | ❌ silent chimera-run death |
| v23 | same | same | 5 + 1 design.md | ❌ 4 test fixture bugs, agent shipped anyway |
| v24 | same | same | 3 + 4 mind/* journals | ❌ skipped tests + remediation.py to dodge "no red tests" rule |

The pattern is stable across attempts: **the load-bearing chain
enforces correctness but does not make the multi-file coordination
problem easier**. The agent reliably ships 2-file scopes; it
unreliably ships 5-file scopes even when the template is in main as a
literal cargo-cult source.

## Hypothesis

A 5-file wiring task decomposed into 5 single-file sub-tasks should
ship under the proven add-one-function shape, in sequence. Each
sub-task is in the v17/v18/v19/v21 success class. The dependency
graph between layers is shallow (typically: ActResult field → call
site → escalation entry / trust delta / remediation hint), so
parallelization is possible but sequencing is also acceptable.

The cost is N×operator-overhead per wiring task (charter authoring
per sub-task, PR review per sub-task) in exchange for higher ship-rate.

## Atomic operation taxonomy

Empirically, "wiring" tasks decompose into a small set of atomic
operations:

| Op | Shape | Typical size | Proven? |
|---|---|---|---|
| **add-field** | Add a new field to an existing dataclass | +5-10 lines | ✅ implied by v17/v18 patterns |
| **add-call-site** | Insert a call to an existing function in an existing place | +5-15 lines | ✅ implied by v19 |
| **add-line** | Add a single entry to a list or dict | +1-2 lines | not yet soak-validated |
| **add-function** | Define a new function in an existing module | +20-50 lines | ✅ v17/v18/v21 |
| **add-test-suite** | New test file or new tests in existing file | +50-200 lines | ✅ paired with all of the above |

Each maps to a 2-file sub-soak (source + tests).

## Dependency graph

For a wiring task that connects detector → ActResult → escalation
→ trust → remediation (the v4.115 / v4.116 shape):

```
add-field (ActResult.X_violations)
   │
   ├─► add-call-site (call detector, populate field)
   │
   ├─► add-line (ESCALATING_FINISH_REASONS entry)
   │
   ├─► add-line (FINISH_REASON_TRUST_DELTAS entry)
   │
   └─► add-function (remediation hint helper + register in dispatch)
```

`add-field` is the root — everything else either references the field
or names the finish_reason that the call site produces. The
add-call-site depends on the field existing. The other three are
independent of each other and of the call site (they take effect
only when the call site fires; until then they're inert).

Sequencing: **A (field) → B (call site)** in order; **C, D, E** in any
order (or in parallel if the operator wants to interleave).

## Branch strategy

Three options:

### Option 1: sequential commits to one branch

All 5 sub-soaks run on the same `chimera-soak/wiring-<task>` branch.
Each sub-soak's PR is a single commit on that branch. After all 5
merge, the branch is fast-forwarded onto main and deleted.

**Pros**: one cohesive feature branch; intermediate state always
makes sense; final history is clean.
**Cons**: PR review is per-commit (5 PRs); each PR's diff is small
but the operator must keep the cumulative picture in mind.

### Option 2: independent branches, sequential merge

Each sub-soak runs on its own branch off main. Each PR merges
independently. The next sub-soak forks from the post-merge main.

**Pros**: each sub-soak is fully self-contained; failure of any
single sub-soak doesn't poison subsequent ones.
**Cons**: each sub-soak's worktree must rebase if main moves between
runs; main accumulates 5 small commits rather than a feature group.

### Option 3: shared base + independent sub-soak branches

Pre-create a `chimera-feat/<task>` parent branch from main. Each
sub-soak forks from this parent. PRs target the parent, not main.
When all 5 are merged into parent, parent merges into main as a
single squash or merge commit.

**Pros**: feature stays grouped; intermediate state is on a branch
not main; rollback is one branch-delete.
**Cons**: most complex; requires extra branch lifecycle management.

**Recommendation**: **Option 2** for the first wiring trial. Simpler
to reason about, matches the existing pattern (each soak ships its
own PR), no new branch lifecycle infrastructure. If the methodology
proves out, Option 3 may be worth revisiting for larger features.

## Failure handling

| Failure mode | Coordinator response |
|---|---|
| Sub-soak hits budget cap | Operator review; usually = agent didn't ship; halt and decide |
| Sub-soak produces dirty PR (charter violation) | Don't merge; halt; do not start next sub-soak |
| Sub-soak ships but tests fail post-merge | Operator decides to revert or hotfix; halt |
| Sub-soak ships clean | Merge; sync; start next sub-soak |
| Coordinator is interrupted (operator Ctrl+C) | Manual resume — coordinator's sequence is operator-facing, not autonomous |

The coordinator is **not autonomous itself**. It's a thin
orchestrator that pauses between sub-soaks for operator review +
merge + sync. The autonomy lives at the sub-soak level.

## Coordinator script

Minimal first cut:

```bash
#!/usr/bin/env bash
# scripts/wiring_coordinator.sh
# Usage: wiring_coordinator.sh <wiring-name> <runner1.sh> <runner2.sh> ...
#
# Runs each sub-soak runner in sequence. After each, the operator
# verifies the resulting PR is clean, merges, syncs main, and presses
# ENTER to continue. Coordinator halts on any non-zero exit.

set -euo pipefail

NAME="$1"; shift
LOG="state/wiring_${NAME}.log"
mkdir -p "$(dirname "$LOG")"

for runner in "$@"; do
    echo "$(date) === launching $runner ===" | tee -a "$LOG"
    if ! bash "$runner" 2>&1 | tee -a "$LOG"; then
        echo "$(date) FAIL: $runner" | tee -a "$LOG"
        exit 1
    fi
    echo "$(date) === $runner done ===" | tee -a "$LOG"
    echo "Verify PR merged + main synced, then press ENTER to continue."
    read -r
done

echo "$(date) wiring '$NAME' complete: ${#@} sub-soaks shipped" | tee -a "$LOG"
```

That's the whole coordinator. ~25 lines. Intelligence is in the
sub-soak runners, not here.

## Charter template per sub-soak

Each sub-soak runner is a copy of `long_cycle_soak_v21.sh` (the
proven minimal-shape template) with these substitutions:

```
TARGET:           one atomic operation from the taxonomy above
SCOPE:            2 files (source + tests)
SOFT_SENTINEL:    those 2 files + `mind/research/*-remediation.md` auto-allow
TEST_CMD:         `uv run pytest <test_file> -q` (must be green, zero failures)
CHARTER #1:       "ONE new <thing> in <source>; ONE test addition in <tests>"
OVERSHOOT TRAPS:  v23 "lying-by-honesty" trap + v24 "skipped tests" trap +
                  v22 "phase-1 commit pollution" trap (covered by PR #11)
```

The charter is short because the scope is tiny. Each sub-soak's
phase-1 design doc can be one paragraph; each phase-2 INBOX can be
under 100 lines.

## Worked example: v4.116 wiring

| Sub-soak | Op | File | Charter |
|---|---|---|---|
| v25 | add-field | `chimera/core/act.py` | "Add `charter_file_count_violations: list[str] = field(default_factory=list)` to `ActResult`. Place alongside `commit_message_drift_claims`." |
| v26 | add-call-site | `chimera/core/act.py` | "Call `check_charter_file_count(...)` after the v4.115 call site; populate `actresult.charter_file_count_violations`; set `finish_reason = 'charter_file_count'` if non-empty." Depends on v25. |
| v27 | add-line | `chimera/core/escalation.py` | "Add `'charter_file_count'` to `ESCALATING_FINISH_REASONS`." |
| v28 | add-line | `chimera/trust/manager.py` | "Add `'charter_file_count': -1` to `FINISH_REASON_TRUST_DELTAS`." |
| v29 | add-function | `chimera/core/remediation.py` | "Add `_charter_file_count_hint(...)` helper; register in `_HINT_BY_REASON`." |

Tests per sub-soak: minimal. v25 tests the field default; v26 tests
the call-site + finish_reason setting; v27/v28 test the registry
membership; v29 tests the hint output.

Estimated cost (based on v17/v18/v19/v21 averages of $0.10/soak):
**~$0.50 total for 5 sub-soaks** vs. ~$0.40 per failed v22/v23/v24
multi-file attempt. The decomposed approach is cheaper AND more
likely to ship.

## Resolved questions

### 1. Self-conflict — RESOLVED: order matters

**Decision**: Ship order is **v25 → v26 → v29 → v27 → v28**.
v27 (escalation entry) and v28 (trust delta) are what make
v4.116 "live" (it can fire and demote). Shipping them LAST means
v25/v26/v29 run under the proven v4.115-only chain. Only the
final two sub-soaks are subject to v4.116; by then the charter
regex has been exercised against 3 successful runs and we have
confidence in its behavior.

### 2. Nomenclature & N counting — RESOLVED: two-tier contract

**Decision**: Amend ADR 0114 to distinguish target classes:

- **autonomous-delivery: atomic** — single-file/single-function
  targets (v17/v18/v19/v21 success class). Each sub-soak counts
  individually. Bar: **N ≥ 5**. Current: **N = 4**.
- **autonomous-delivery: composed** — multi-file coordinated
  wiring tasks shipped via the decomposition methodology. The
  composite wiring (all sub-soaks shipping cleanly) counts as 1.
  Bar: **N ≥ 3**. Current: **N = 0**.

v25-v29 each count toward the atomic tier as they ship. The
full v4.116 wiring, if all 5 ship, counts as the first composed
delivery.

### 3. Operator cadence — RESOLVED: auto-merge on green

**Decision**: Coordinator auto-merges sub-soak PRs when BOTH:
- The sub-soak's soft-sentinel exit fired (charter-clean commit
  + targeted test green); AND
- `uv run pytest -q` on the post-push branch head reports zero
  failures across the full suite.

Implementation: after each sub-soak ships, coordinator pushes
the branch, opens the PR, runs the full suite locally on the
branch head, and `gh pr merge --squash --delete-branch` if both
gates pass. Operator intervenes only when the coordinator halts
on failure.

This is a substantive automation step. Trade-off: faster
throughput vs. less per-PR oversight. The justification is that
the soft-sentinel + full-suite combo is a strong signal — if
both pass, the work is by definition shippable under the
existing contract.

### 4. Generalization limits — RESOLVED: `add-coupled-pair` primitive

**Decision**: Extend the atomic-op taxonomy with a
`add-coupled-pair` primitive for cases where two source files
genuinely must ship together (e.g., a public API in one module
+ its test fixtures in another module that constructs instances
via that API).

Updated taxonomy:

| Op | Shape | Typical size | Files |
|---|---|---|---|
| **add-field** | Add a new field to existing dataclass | +5-10 lines | 2 |
| **add-call-site** | Insert call to existing function in existing place | +5-15 lines | 2 |
| **add-line** | Add a single entry to a list or dict | +1-2 lines | 2 |
| **add-function** | Define a new function in existing module | +20-50 lines | 2 |
| **add-test-suite** | New test file or new tests in existing file | +50-200 lines | 1 |
| **add-coupled-pair** | Two source files that must ship together (new API + its fixtures) | +30-100 lines | 4 |

The `add-coupled-pair` charter pattern: 4 files (2 source + 2
tests). The agent must treat the pair as a single atomic unit —
either both layers ship or neither does. Soft-sentinel whitelist
covers all 4 files explicitly; tests must be green on the
combined surface.

This generalizes the methodology beyond v4.115/v4.116's clean
5-layer decomposition. Truly indecomposable wiring (tasks with
cycles deeper than a pair) still falls back to hand-authoring
under operator authorship.

## Refinements after first run

If v25 ships cleanly, the resolutions above hold. If v25
surfaces a new gap (e.g., `add-field` isn't actually atomic
because adding to a dataclass also requires updating
constructors elsewhere), this section gets the post-mortem.

## Next step

If the operator approves this methodology, the immediate work is:

1. Build `scripts/long_cycle_soak_v25.sh` — the ActResult-field
   sub-soak (smallest atomic step).
2. Launch v25.
3. Observe whether the decomposition methodology produces a clean
   ship in the proven 2-file shape.
4. If yes → build v26-v29 from the same template.
5. If no → revisit assumptions (is `add-field` really a proven
   shape, or does it need its own validation?).

Either outcome is informative.
