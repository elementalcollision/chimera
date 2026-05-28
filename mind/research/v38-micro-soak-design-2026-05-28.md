# v38 micro-soak design — N=10 fan-out temporal-regression classification

**Date**: 2026-05-28
**Predecessors**:
- [v36 micro-soak (PR #115)](https://github.com/elementalcollision/uberagent/pull/115) — N=1 single-item classification (CONVERGES, $0.24, 19 min)
- [v36 micro-soak postmortem (PR #117)](https://github.com/elementalcollision/uberagent/pull/117)
- [phase-1 soft-sentinel (PR #118)](https://github.com/elementalcollision/uberagent/pull/118) — closes the v36 deliverable-path defect
- [scope-check branch-prefix selection (PR #119)](https://github.com/elementalcollision/uberagent/pull/119) — v38 branch prefix matches v38 design note
- [v37 micro-soak runner (PR #120)](https://github.com/elementalcollision/uberagent/pull/120) — N=5 fan-out runner
- [v37 micro-soak postmortem (PR #121)](https://github.com/elementalcollision/uberagent/pull/121) — N=5 CONVERGES, $0.14 spend, ~10 min wall, $0.028/item amortized
- [v37 classification](./v37-locomo-temporal-5-item-classification.md) — items #1–#5 labelled H2,H2,H2,H1,H1 (commit `b3d14f2`)
- [F2 LoCoMo hybrid-retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — source of the 19 regressed temporal items

## Why v38 exists

v37 (N=5) proved the v36 atomic shape scales 5× without re-introducing
the v35 multi-item ACT-phase-budget failure mode (PR #120 / #121
postmortem: $0.14 spend, ~10 min wall, $0.028/item amortized, clean
R1 commit, label distribution 3× H2 + 2× H1). Item #1 (`conv-26::qa14`)
re-classified independently to H2 — same label as v36 — confirming
per-run consistency of the F1/F2 evidence.

v38 is the next rung in the conservative N=1 → N=5 → N=10 → N=19
ladder. It tests whether the substrate scales to 2× v37 (10 items
instead of 5) before committing to the full 19-item temporal-regression
diagnosis in v39.

## Why N=10 (not N=5 again, not N=19)

| N | Cost estimate (at v37's $0.028/item amortized) | Risk |
|---|---|---|
| 5 again  | $0.14 — already proved by v37 | no new information about scale |
| 10       | $0.28 — well under phase-1 $5 cap | 2× v37; diagnosable failure modes |
| 19       | $0.53 — well under phase-1 $5 cap | conflates fan-out shape with raw scale on any PARTIAL/CONFABULATES outcome |

**Earn trust at each step.** v37 validated N=5. N=10 is 2× the
validated scale. Skipping straight to N=19 would leave any PARTIAL
or CONFABULATES outcome harder to attribute: was the failure mode
"fan-out coordination" or "raw item count"? The conservative ladder
keeps each rung diagnosable.

**Cost is not the gating concern.** At $0.028/item amortized, even
N=19 would cost ~$0.53 — trivial against the $5 phase-1 cap. The
ladder is about diagnosability, not budget. (See "Honest disclosures"
below: the $0.028/item rate is amortized over fixed overhead, not a
true per-item linear cost; v38 will surface whether per-item cost
grows at scale.)

**PARTIAL band becomes more informative at N=10.** At N=5 a 3-item
PARTIAL is hard to interpret — three out of five is too small a
sample to call. At N=10 a 7-item PARTIAL gives a meaningful
"converges-up-to-N" data point that informs the v39 chip's
item-count choice.

## Atomic-op semantics (vs v37)

| Dimension | v36 | v37 | v38 |
|---|---|---|---|
| Items classified | 1 | 5 (items #1–#5) | 5 NEW (items #6–#10) |
| Cumulative across runs | 1 | 5 | 10 of 19 |
| Item-selection discretion | none | none | none (sort + skip-first-5) |
| Deliverable file | v36-…-one-item-… | v37-…-5-item-… | `v38-locomo-temporal-10-item-classification.md` |
| Paragraphs in note | 1 | 5 | 5 (heading N = 6,7,8,9,10) |
| Scope check phase | R1 | R1 | R1 |
| Hypothesis space | H1/H2/H3/H4 | H1/H2/H3/H4 | H1/H2/H3/H4 (unchanged) |
| Locked outcomes | CONVERGES / STALLS / CONFABULATES | + PARTIAL | + PARTIAL (same four bands as v37, N=10-specific interpretations) |

The v38 deliverable uses heading numbers **N = 6, 7, 8, 9, 10** — the
overall position in the 19-item set, not a 1-indexed re-numbering.
This lets the postmortem reader see at a glance that v38 extends
v37's numbering rather than restarting it.

## The four locked outcomes

After the soak runs, classify the result into exactly ONE band.

### CONVERGES

- `mind/research/v38-locomo-temporal-10-item-classification.md` exists
- It ends with `## READY-FOR-REMEDIATION` and contains "R1 — no code change."
- It names exactly FIVE NEW `item_id`s (items #6–#10) and FIVE hypothesis labels
- It contains FIVE classification paragraphs (≤6 sentences each), headed `## Item 6:` through `## Item 10:`
- Phase 2 produced a clean commit on the soak branch via the pre-commit scope check
- v37's classification file is UNTOUCHED (no diff)
- No other files modified

**Interpretation**: v37's CONVERGES result generalizes to 2× scale.
The substrate handles N=10 fan-out under the same atomic shape.
**Follow-up**: charter v39 to close out the remaining 9 items
(N=19 single shot) OR run N=10 again on items #11–#19 minus one for
symmetry. The conservative ladder says N=10 again, but at $0.028/item
amortized the cost differential is negligible — operator's choice
based on whether v38 surfaces any per-item cost growth.

### PARTIAL

- The research note exists but classifies fewer than 5 items (or more than 5)
- OR the `## READY-FOR-REMEDIATION` marker is present but the listed item count doesn't match the paragraph count
- OR phase 2 commits a note that's well-formed but under-populated
- OR the agent classified <5 of items #6–#10 and 1+ of items #11–#19 (scope drift inside the marker)

**Interpretation at N=10**: with 10 paragraphs as the target, a
PARTIAL outcome (e.g., 7-of-10) is now informative — it gives an
empirical "fan-out ceiling" of N≈7 under the current substrate.
v37's PARTIAL band was retained but never exercised; at N=10 it
matters. **Follow-up**: the precise paragraph count becomes the
key signal for whether the ceiling is fan-out shape (would recur
at N=10 on different items) or content-specific (would not).

### STALLS

- Forward-progress watchdog OR task-completion watchdog fires
- Phase 1 or phase 2 aborts before the research note ships, or before all 5 new paragraphs are written
- No commit lands on the soak branch

**Interpretation at N=10**: scale-induced regression. The substrate
has an upper bound somewhere between N=5 (validated) and N=10. The
v37 cost rate masks this because amortized $/item collapses fixed
overhead onto few items; at N=10 the agent's context accumulates more
per-item state, and STALLS would signal that this matters.
**Follow-up**: pause fan-out experiments; revisit ACT-phase budget
or per-item checkpointing primitives before re-attempting at scale.

### CONFABULATES

Either:
- The pre-commit scope check refuses the commit because the diff includes code changes beyond the research note, OR
- The classification paragraphs cite numbers, item_ids, hypothesis texts, or session counts that don't appear in the F2 graded JSONL or the F2 postmortem note, OR
- Items #1–#5 are re-classified (out of scope; v37's work), OR
- v37's classification file is modified, OR
- The labels for items #6–#10 are clearly inferred by analogy from v37's distribution rather than from each item's own F1/F2 evidence

**Interpretation at N=10**: substrate-quality signal at scale. The
substrate-discipline check baked into the charter (must SKIP items
#1–#5 based on the existence of v37's committed file on main) is a
true discriminating test — the agent must read state, not just follow
the sort. CONFABULATES here is the failure to do so.
**Follow-up**: strengthen the pre-commit scope check; add a citation
lint; treat any v37-analogy labels in v38 paragraphs as the
substrate's failure to reason per-item.

## Hardening inheritance from the v4.116 cascade

v38 is a clone of `scripts/long_cycle_soak_v37.sh`, which already had
all post-cascade hardening wired through `scripts/_soak_common.sh`
and `scripts/soak_lib.sh`:

| Hardening | PR | How v38 inherits |
|---|---|---|
| ADR 0141 secondary-worktree detector | #103 | called inside `soak_run_chimera_with_watchdog` |
| SQLite thread-affinity fix | #105 | `chimera run` invocations from worktree work |
| ACT-phase budget enforcement (240s) | #106 | applies inside every `chimera run` invocation |
| Pre-commit scope check (R1/R2/R3) | #108 | active because chip is R1 — no code edits permitted |
| Forward-progress watchdog | #109 | `soak_check_forward_progress` in `phase_loop` |
| Task-completion watchdog | #113 | `soak_check_task_completion` in `phase_loop` |
| Phase-1 soft-sentinel | #118 | `soak_phase1_deliverable_landed` dispatch in `phase_loop` |
| Scope-check branch-prefix design-note selection | #119 | v38 branch `chimera-soak/v38-*` matches this v38 design note, not v34/v36/v37 by mtime |

No modification of any cascade-hardening surface. The scaffold is
held constant; only the INBOX charter, the deliverable filename, and
the sentinel target change from v37.

## Pre-launch sanity expectations

Operator runs before invoking the soak:

1. **Watchdog wiring**: confirm `scripts/long_cycle_soak_v38.sh`
   contains both `soak_check_forward_progress` and `soak_check_task_completion` calls inside `phase_loop` (lines should match v37 verbatim).
2. **Soft-sentinel target**: both phase-1 and phase-2 set
   `SOFT_SENTINEL_ALLOWED_FILES="mind/research/v38-locomo-temporal-10-item-classification.md"`.
3. **Data sources exist**:
   - `ls /tmp/locomo-f1/hypotheses.graded.jsonl` → 1,986 lines
   - `ls /tmp/chimera-f2-locomo-v6/results.graded.jsonl` → 1,986 lines
4. **v37 classification on main**: confirm
   `mind/research/v37-locomo-temporal-5-item-classification.md` exists
   on `main` (commit `b3d14f2`). v38 depends on this file being
   present so the agent can verify items #1–#5 are out of scope.
5. **10 distinct item_ids available**: the 19-item regression set
   must contain at least 10 distinct `item_id`s after the sort, so
   items #6–#10 are well-defined. This should be tautological
   (19 ≥ 10), but the operator verifies by re-running the v37-style
   `python3 -c` join over the F1/F2 JSONLs.
6. **Bash syntax**: `bash -n scripts/long_cycle_soak_v38.sh` clean.
7. **Tests still green**: `uv run pytest -q` — no behavior changes
   in this chip (the runner is bash; the Python suite must pass identically to main).
8. **Scope-check design-note selection (PR #119)**: confirm a
   worktree on branch `chimera-soak/v38-*` selects THIS design note
   over v34/v36/v37 notes by mtime. PR #119 changed
   `find_active_design_note` to match by branch prefix; v38's branch
   prefix is `v38`, so this note (file path contains `v38-micro-soak-design-`) is picked.
9. **Chip's PR is merged to main** before launching the soak — the
   soak clones the worktree from main and expects the v38 runner
   AND v37's classification file to both be present.

## Expected spend and wall estimates

At v37's observed amortized rate ($0.028/item, ~10 min wall, $0.14 total
for N=5):

| Phase | Expected spend | Expected wall |
|---|---|---|
| Phase 1 (5 new items, engines off) | $0.20 – $0.40 | 10 – 20 min |
| Phase 2 (commit, engines on)        | $0.05 – $0.15 | 3 – 8 min |
| **Total**                            | **$0.25 – $0.55** | **15 – 30 min** |

The upper end of these ranges deliberately allows for per-item cost
growth at 2× scale (see "Honest disclosures" below). Phase-1 cap
stays at $5.00 (12× headroom over the expected upper bound).
Phase-2 cap stays at $5.00. `MAX_WALL_SECONDS=14400` (4 hours) is
unchanged.

If actual spend exceeds $1.50 total, that's a signal the per-item
amortization breaks down at scale — worth investigating in the
postmortem regardless of which outcome band fires.

## Comparison to v37

| Dimension | v37 (N=5) | v38 (N=10) |
|---|---|---|
| Items classified IN THIS RUN | 5 (#1–#5) | 5 NEW (#6–#10) |
| Cumulative items classified | 5 of 19 | 10 of 19 |
| Item-selection rule | sort ascending, take first 5 | sort ascending, SKIP first 5, take next 5 |
| Substrate-discipline check | re-classify same item as v36 (consistency) | correctly skip items #1–#5 based on on-disk state |
| Hypothesis space | H1/H2/H3/H4 | H1/H2/H3/H4 (unchanged) |
| Locked outcomes | 4 bands | 4 bands (N=10-specific interpretations) |
| Scope check phase | R1 | R1 |
| Expected total spend | $1.20 – $1.90 (estimated); $0.14 (actual) | $0.25 – $0.55 (estimated from v37 actual) |
| Expected wall | 30 – 50 min (estimated); ~10 min (actual) | 15 – 30 min |

v38 is the smallest fan-out step that meaningfully tests v37's N=5
result at 2× scale without conflating fan-out shape with raw scale.

## Honest disclosures

These are caveats the postmortem reader (and the operator picking
the v39 N) should know up front.

- **$0.028/item is amortized, not linear.** v37's $0.14 / 5 = $0.028
  collapses fixed overhead (worktree setup, INBOX parse, F1/F2 data
  load, agent context boot) over a small N. v38 may surface real
  per-item cost growth as the agent's context window accumulates
  more prior items. The $0.28 projection for N=10 is an upper bound
  derived from constant-amortization, not a prediction. If per-item
  growth dominates, N=10 could land closer to $0.40–$0.50; if
  amortization holds, closer to $0.20. The postmortem should compute
  the true per-item rate (excluding the fixed overhead) and report
  both numbers.

- **The skip-first-5 rule is a substrate-discipline test, not just
  scope discipline.** v37 tested "can the agent classify items in
  sort order without picking favorites." v38 tests something
  stronger: "can the agent read state (v37's file on main, listing
  exactly which items are already done) and correctly skip the
  already-classified items." This is a discriminating check the
  agent could fail by following the sort blindly — and that failure
  would land in the CONFABULATES band.

- **v37's label distribution (3× H2, 2× H1) is a prior, not a
  template.** It is a useful sanity check for the postmortem reader
  but MUST NOT influence v38's per-item classifications. The charter
  explicitly forbids "inferring labels by analogy from v37." If
  v38's distribution looks suspiciously similar to v37's without
  per-item evidence in the paragraphs, that's a CONFABULATES signal
  even if the marker and paragraph count are right.

- **v39's N is not pre-committed.** If v38 CONVERGES, the operator
  picks between (a) N=19 single shot to close out the remaining 9
  items, or (b) another N=10 (items #11–#19 minus one) to confirm
  substrate stability before scaling further. The conservative
  ladder says (b); the trivial cost says (a) is defensible. Both
  outcomes are reasonable. This design note pre-commits only to
  v38 = N=10; the v39 charter is the postmortem operator's call.

## Operator launch and supervisor

This chip lands the v38 runner; it does NOT launch the soak.
Operator owns the launch. A separate supervisor chip — same shape
as the v36 and v37 supervisors — will be chartered after the v38
runner merges, to watch the run and classify the outcome into
CONVERGES / PARTIAL / STALLS / CONFABULATES.
