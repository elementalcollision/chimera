# v37 micro-soak design — N=5 fan-out temporal-regression classification

**Date**: 2026-05-28
**Predecessors**:
- [v36 micro-soak (PR #115)](https://github.com/elementalcollision/uberagent/pull/115) — N=1 single-item classification (CONVERGES)
- [v36 micro-soak postmortem (PR #117)](https://github.com/elementalcollision/uberagent/pull/117) — $0.24, 19 min, one clean R1 commit
- [phase-1 soft-sentinel (PR #118)](https://github.com/elementalcollision/uberagent/pull/118) — closes the v36 deliverable-path defect
- [scope-check branch-prefix selection (PR #119)](https://github.com/elementalcollision/uberagent/pull/119) — v37 branch prefix matches v37 design note, not v34/v36 by mtime
- [F2 LoCoMo hybrid-retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — source of the 19 regressed temporal items
- [v36 prior classification](./v36-locomo-temporal-one-item-classification.md) — the H2 label for `conv-26::qa14` that v37 item #1 must reproduce independently

## Why v37 exists

v36 (N=1) proved the substrate can converge on a single atomic
LoCoMo F2 temporal-reasoning classification under the post-cascade
hardening (PR #115 / #117 postmortem: $0.24, 19 minutes, one clean
R1 commit). The v36 design note's CONVERGES band closed with an
explicit follow-up: "charter a v37 chip that fans out to 5 items
per soak, preserving the sort-first item-selection rule."

v37 is that follow-up.

## Why N=5 (not 1, not 19)

| N | Cost estimate (at v36's $0.24/item rate) | Risk |
|---|---|---|
| 1  | $0.24 | already proved by v36 — no new information |
| 5  | $1.20 — well under phase-1 $5 cap | fan-out test with budget headroom |
| 19 | $4.56 — bumps against phase-1 $5 cap | fragile; one cycle blowout exceeds cap |

N=5 fits comfortably in the existing phase-1 budget (the cap stays
at $5 for parity with v36's runner; the new headroom absorbs per-
cycle variance). N=19 would consume the entire chartered budget in
the happy path, leaving zero room for the kind of foraging-overhead
that re-introduces the v35 multi-item failure mode. N=5 is the
smallest fan-out that exercises the loop-resets-between-items shape
without saturating the budget.

## Built-in consistency check

Item #1 is `conv-26::qa14` — the same item v36 classified as H2
(context-budget dilution). v37's INBOX explicitly forbids copying
v36's label and instructs the agent to classify item #1 independently
from the F1/F2 data. If v37 lands H2 for item #1, that's a per-run
consistency signal — the same evidence produces the same label.
If v37 lands a different label, the operator inspects v36 vs v37
side-by-side and decides whether the divergence is data-justified
or a substrate-quality signal.

This is a free consistency check baked into the fan-out shape: no
extra mechanism, just sort-first item selection landing the same
first item v36 hit.

## Atomic-op semantics (vs v36)

| Dimension | v36 | v37 |
|---|---|---|
| Items classified | 1 (sort-first) | 5 (items 1-5 by sort) |
| Item-selection discretion | none | none |
| Deliverable file | `v36-locomo-temporal-one-item-classification.md` | `v37-locomo-temporal-5-item-classification.md` |
| Paragraphs in note | 1 | 5 (one per item, each headed `## Item N: <id> → <label>`) |
| Scope check phase | R1 | R1 |
| Hypothesis space | H1/H2/H3/H4 | H1/H2/H3/H4 (same labels) |
| READY-FOR-REMEDIATION content | one item_id + one label | five item_ids + five labels |
| Locked outcomes | CONVERGES / STALLS / CONFABULATES | CONVERGES / **PARTIAL** / STALLS / CONFABULATES |

The new **PARTIAL** band recognizes the fan-out-specific failure
mode where the loop converges on *some* items but not all five.
v36 had no such band because N=1 admits only converge-or-not.

## The four locked outcomes

After the soak runs, classify the result into exactly ONE band.

### CONVERGES

- `mind/research/v37-locomo-temporal-5-item-classification.md` exists
- It ends with `## READY-FOR-REMEDIATION` and contains "R1 — no code change."
- It names exactly FIVE `item_id`s and FIVE hypothesis labels (H1/H2/H3/H4 each)
- It contains FIVE classification paragraphs (≤6 sentences each), one per item, ordered by item_id sort
- Phase 2 produced a clean commit on the soak branch via the pre-commit scope check
- No other files modified

**Interpretation**: v36's CONVERGES result generalizes to N=5 fan-out.
The atomic shape scales without re-introducing the v35 multi-item
ACT-phase-budget failure mode. **Follow-up**: charter v38 to fan out
further (e.g. N=10 or N=19) and re-evaluate budget headroom.

### PARTIAL

- The research note exists but classifies fewer than 5 items (or more than 5)
- OR the `## READY-FOR-REMEDIATION` marker is present but the listed item count doesn't match the paragraph count
- OR phase 2 commits a note that's well-formed but under-populated

**Interpretation**: the substrate handled the per-item shape but the
fan-out coordination failed. The watchdogs didn't fire (each iter made
forward progress) but the agent emitted the marker prematurely. This
is a NEW failure mode that N=1 could not surface. **Follow-up**:
strengthen the soft-sentinel to gate on paragraph count, not just
file presence + marker presence.

### STALLS

- Forward-progress watchdog OR task-completion watchdog fires
- Phase 1 or phase 2 aborts before the research note ships, or before all 5 paragraphs are written
- No commit lands on the soak branch

**Interpretation**: fan-out exceeded what the substrate can complete
autonomously, even at N=5. v36's N=1 success was the ceiling.
**Follow-up**: pause fan-out experiments; revisit ACT-phase budget
or per-item checkpointing primitives before re-attempting.

### CONFABULATES

Either:
- The pre-commit scope check refuses the commit because the diff includes code changes beyond the research note, OR
- The classification paragraphs cite numbers, item_ids, hypothesis texts, or session counts that don't appear in the F2 graded JSONL or the F2 postmortem note, OR
- Item #1's label is verbatim-copied from v36 without independent reasoning visible in the paragraph

**Interpretation**: substrate produces work but can't be trusted to
stay within scope, cite real data, or reason independently when given
a hint. The scope check + operator catch it before it ships.
**Follow-up**: strengthen the pre-commit scope check; add a citation
lint; consider whether the v36-pointer in INBOX is a confabulation
attractor (and if so, remove it from future fan-out runners).

## Hardening inheritance from the v4.116 cascade

v37 is a clone of `scripts/long_cycle_soak_v36.sh`, which already had
all post-cascade hardening wired through `scripts/_soak_common.sh`
and `scripts/soak_lib.sh`:

| Hardening | PR | How v37 inherits |
|---|---|---|
| ADR 0141 secondary-worktree detector | #103 | called inside `soak_run_chimera_with_watchdog` |
| SQLite thread-affinity fix | #105 | `chimera run` invocations from worktree work |
| ACT-phase budget enforcement (240s) | #106 | applies inside every `chimera run` invocation |
| Pre-commit scope check (R1/R2/R3) | #108 | active because chip is R1 — no code edits permitted |
| Forward-progress watchdog | #109 | `soak_check_forward_progress` in `phase_loop` |
| Task-completion watchdog | #113 | `soak_check_task_completion` in `phase_loop` |
| Phase-1 soft-sentinel | #118 | `soak_phase1_deliverable_landed` dispatch in `phase_loop` |
| Scope-check branch-prefix design-note selection | #119 | v37 branch `chimera-soak/v37-*` matches this v37 design note, not older v34/v36 notes by mtime |

No modification of any cascade-hardening surface. The scaffold is
held constant; only the INBOX charter, the deliverable filename, and
the sentinel target change.

## Pre-launch sanity expectations

Operator runs before invoking the soak:

1. **Watchdog wiring**: confirm `scripts/long_cycle_soak_v37.sh`
   contains both `soak_check_forward_progress` and `soak_check_task_completion` calls inside `phase_loop` (lines should match v36 verbatim).
2. **Soft-sentinel target**: both phase-1 and phase-2 set
   `SOFT_SENTINEL_ALLOWED_FILES="mind/research/v37-locomo-temporal-5-item-classification.md"`.
3. **Data sources exist**:
   - `ls /tmp/locomo-f1/hypotheses.graded.jsonl` → 1,986 lines
   - `ls /tmp/chimera-f2-locomo-v6/results.graded.jsonl` → 1,986 lines
4. **Bash syntax**: `bash -n scripts/long_cycle_soak_v37.sh` clean
5. **Tests still green**: `uv run pytest -q` — no behavior changes
   in this chip (the runner is bash; the Python suite must pass identically to main).
6. **Scope-check design-note selection (PR #119)**: confirm that a
   worktree on branch `chimera-soak/v37-*` selects THIS design note
   over `v34-*` / `v36-*` notes by mtime. PR #119 changed
   `find_active_design_note` to match by branch prefix; v37's branch
   prefix is `v37`, so this note (file path contains `v37-micro-soak-design-`) is picked.
7. **Chip's PR is merged to main** before launching the soak — the
   soak clones the worktree from main and expects the v37 runner
   to be present.

## Expected spend and wall estimates

At v36's observed rate ($0.24 per atomic-classification cycle, 19 min wall):

| Phase | Expected spend | Expected wall |
|---|---|---|
| Phase 1 (5 items, engines off) | $1.00 – $1.50 | 25 – 40 min |
| Phase 2 (commit, engines on)   | $0.20 – $0.40 | 5 – 10 min |
| **Total**                       | **$1.20 – $1.90** | **30 – 50 min** |

Phase-1 cap stays at $5.00 (5x headroom over expected). Phase-2 cap
stays at $5.00 (parity with v36 — commit-only phase is cheap).
`MAX_WALL_SECONDS=14400` (4 hours) is unchanged; we expect to finish
in well under one hour.

If actual spend exceeds $3.00 total, that's a signal worth
investigating in the postmortem regardless of which outcome band
fires.

## Comparison to v36

| Dimension | v36 (N=1) | v37 (N=5) |
|---|---|---|
| Items classified | 1 | 5 |
| Hypothesis space | H1/H2/H3/H4 | H1/H2/H3/H4 (same labels) |
| Item-selection discretion | none (sort-first) | none (sort-first, take 5) |
| Locked outcomes | CONVERGES / STALLS / CONFABULATES | CONVERGES / PARTIAL / STALLS / CONFABULATES |
| Built-in consistency check | n/a | item #1 = v36's item; independent re-classification expected |
| Scope check phase | R1 | R1 |
| Expected total spend | $0.24 (actual) | $1.20 – $1.90 |
| Expected wall | 19 min (actual) | 30 – 50 min |

v37 is the smallest fan-out that meaningfully tests the v36 atomic
shape's scaling properties.

## Operator launch and supervisor

This chip lands the v37 runner; it does NOT launch the soak.
Operator owns the launch. A separate supervisor chip — same shape
as the v36 supervisor — will be chartered after the v37 runner
merges, to watch the run and classify the outcome into
CONVERGES / PARTIAL / STALLS / CONFABULATES.
