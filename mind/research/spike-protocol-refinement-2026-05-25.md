# Spike protocol refinement — stratified sampling + per-category gates (2026-05-25)

**Purpose**: Meta-research note. Refine the n=30 category-localized spike
protocol that ADR 0138 used twice (PR #72→#73 v1; PR #75→#76 v2) and that
[PR #77](https://github.com/elementalcollision/chimera/pull/77)'s corpus
sweep falsified. Output: a stratified-spike protocol with per-category
gates and a corpus-promotion criterion, plus a decision tree for which
protocol future chips should adopt.

This note is the design input to [ADR 0140](../../docs/adr/0140-stratified-spike-protocol.md).
No code, tests, or CLI surfaces are shipped in this chip — only methodology.

---

## TL;DR

The category-localized spike protocol (ADR 0138, n=30 in target category
only) has two structural blind spots:

1. **Category-localized**: it measures only the target category, so it
   cannot detect collateral damage in the other five LongMemEval task
   shapes.
2. **Per-item noisy at n=30**: with ~3-5 items flipping in either
   direction under no real effect, single-item gates ("Gate B = 0
   regressions") are load-bearing on stochastic outcomes.

PR #77 cost $2 of corpus measurement to surface a 4-item knowledge-update
regression that the n=30 SPP-only spike literally could not see. The
refined protocol stratifies sampling across all six LongMemEval categories
(~3-5 items each, total n≈18-30) and adds per-category gates with a
corpus-promotion criterion. Cost stays comparable (~$0.05-$0.08) but the
spike now measures the surface area where collateral damage actually
lives.

The refined protocol is itself imperfect — per-category n=3-5 has wider CIs
than the old n=30, so it will sometimes return "ambiguous, cheap corpus
recommended." That is the explicit, accepted outcome; it is strictly
better than the old protocol's "PASS at category, surprise FAIL at
corpus."

---

## Section 1 — Protocol limitation evidence

### The PR #76 → PR #77 disagreement (quantitative)

| Measurement | n | SPP delta | Overall delta | Off-target signal |
|---|---:|---:|---:|---|
| PR #73 spike v1 (n=30 SPP-only) | 30 | n/a (Gate B FAIL: 5 right→wrong) | unmeasured | unmeasured (category-localized) |
| PR #76 respike v2 (n=30 SPP-only) | 30 | +6.67pp net (3W/1L) | unmeasured | unmeasured (category-localized) |
| PR #77 corpus (n=500) | 500 | **+10.00pp** | **−0.80pp** | **knowledge-update −5.13pp (4 items), multi-session −1.50pp (2), single-session-user −1.43pp (1)** |

Two distinct failure modes are visible:

**Failure mode (a) — category-localized.** The spike measures only the
target category. The +10.00pp corpus SPP gain is in the same direction as
the spike v2 result, so the spike directionally validated. But the **−4
items aggregate net** is dominated by knowledge-update (−4 alone, the same
4 items), a category the spike's measurement set did not include. No
amount of post-hoc per-item analysis on the n=30 SPP set could have
surfaced this.

**Failure mode (b) — per-item noise.** Within SPP itself, the spike v2
saw 3 wins / 1 loss; the corpus saw 3 wins / 0 losses. Only **1 of the 4
spike "flips" (`d24813b1`) reproduced literally at corpus**. The spike's
"win" set (`6b7dfb22`, `75832dbd`, `d24813b1`, `95228167`†) and the corpus
"win" set (`75f70248`, `95228167`, `d24813b1`) share only 2 items. The
spike's "loss" (`d6233ab6`, framed as a "known outlier") did not
reproduce. The Gate B FAIL framing in PR #76 was load-bearing on a
non-reproducing flip.

† `95228167` was actually wrong in spike v2 too on re-inspection; the
spike's true count was 3W/1L. The point stands.

### What this implies

- The protocol **direction-signal** is reliable at n=30 (both spike runs
  flagged SPP as positively-affected; corpus agreed).
- The protocol **per-item gate-tracking** is not portable. Binary
  thresholds like "Gate B = 0 regressions" rest on outcomes that may not
  reproduce at corpus.
- The protocol **off-target measurement** is structurally absent.
  Whatever the heuristic does to non-target categories is invisible until
  $2 of corpus runs.

These are protocol design problems, not heuristic-quality problems. Even
a perfectly-engineered v3 implicit-preference heuristic, evaluated under
the same protocol, could re-encounter the same surprise.

---

## Section 2 — Refined protocol spec

### 2.1 Stratified sampling

**Construction**: select N items per LongMemEval category from the
oracle JSONL, balanced across the six categories
(`knowledge-update`, `multi-session`, `single-session-assistant`,
`single-session-preference`, `single-session-user`, `temporal-reasoning`).

**Default**: `per_category = 4` → total n=24. Acceptable range:
`per_category ∈ [3, 5]`, total n ∈ [18, 30]. The total stays in the same
cost envelope as the old protocol (~$0.05-$0.08 per spike).

**Item-selection determinism**: take the **first N items of each
category** in the oracle JSONL order. The oracle file order is stable
across runs; this gives every chip in the lineage the same spike set,
making spike-to-spike comparisons meaningful and avoiding cherry-pick
concerns. Future chips that want a different stratified slice should
amend this protocol with explicit rationale, not pick ad-hoc.

**Implementation surface** (sketch, not shipped here):

```python
def stratified_subset(
    items: Iterable[LongMemEvalItem],
    *,
    per_category: int = 4,
    categories: Sequence[str] | None = None,
) -> list[LongMemEvalItem]:
    """Return the first ``per_category`` items per category.

    ``categories`` defaults to the six known LongMemEval shapes.
    Items lacking a category attribute are dropped silently
    (consistent with how `run_batch`'s subset filter treats them).
    Stable order: input order preserved within each category.
    """
```

`chimera/evals/longmemeval.py` already exposes `per_category_limit` on
`run_batch`, which gives the same outcome when paired with the full
oracle JSONL. A separate `stratified_subset` helper is *not strictly
required* — invoking `run_batch(items, per_category_limit=4)` against the
oracle achieves stratified n=24. The helper is desirable for callers
that want to build the subset offline (e.g. cache spike-eval prompts,
inspect the set before running) but is **out of scope for this chip**.
Document the existing `per_category_limit` path as the supported MVP.

### 2.2 Per-category gates

Replace the single global `Gate A` / `Gate B` (paired-item, target
category only) with a structured per-category gate table.

**Target category** (the category the intervention is designed to help):

| Gate | Threshold (paired vs pre-intervention baseline) |
|---|---|
| T-Win | wrong→right flips ≥ `T_win` (default: ≥1 of n=4 in target category, i.e. ≥25% wins rate) |
| T-Loss | right→wrong flips ≤ `T_loss` (default: 0 of n=4) |

Looser per-item thresholds than the old protocol because per-category n
is now 4, not 30. The gate is "did the intervention move SOME items in
the right direction without breaking any?" — directional, not aggregate.

**Off-target categories** (the other five):

| Gate | Threshold (paired vs pre-intervention baseline) |
|---|---|
| O-Loss-per-cat | right→wrong flips ≤ 1 per category (default; tunable per chip) |
| O-Loss-aggregate | total right→wrong flips across off-target ≤ 2 |

The dual threshold catches both **concentrated regressions** (≥2 losses
in any single off-target category — what PR #77 would have surfaced;
knowledge-update lost 4) and **broad-but-shallow noise** (1 loss each
across multiple off-target categories — the multi-session/single-session-user
shape).

**Aggregate gate** (the safety net):

| Gate | Threshold |
|---|---|
| A-Net | net wins-minus-losses across ALL categories ≥ 0 |

This catches the case where the target category produces wins matching
T-Win but off-target losses still net the chip negative.

**All three gate categories must clear for the spike to PASS.** A spike
PASS does **not** authorize a `main` merge — it authorizes a corpus run
(see §2.3).

### 2.3 Corpus-promotion criterion

A clean spike PASS in §2.2 means: "the intervention has positive
directional signal in the target category, no concentrated off-target
damage, and net-positive across the stratified sample." This is
significantly stronger evidence than the old category-localized PASS,
but it is still n=18-30; concentrated off-target regressions at the
3-5 item-per-category resolution still slip through.

**Corpus-promotion criterion**: when the stratified spike PASSes, the
chip MAY proceed to a 500-item full-corpus run **before** any `main`
merge. The corpus run's promotion gate stays as ADR 0138's PR #76 dual
gate (overall ≥ regression-floor AND target ≥ target-threshold), per the
PR #77 lesson that corpus measurement is the final word.

**Critically**: a stratified spike PASS is **necessary but not
sufficient** for promotion. The corpus measurement remains the actual
release gate. The stratified spike's role is to **avoid burning $2 on
corpus runs that the spike could have predicted would fail**.

### 2.4 Abort criterion

When the stratified spike fails any of §2.2's gates, the chip aborts
without spending corpus budget. Specifically:

| Failure mode | Diagnosis | Action |
|---|---|---|
| T-Win fails | intervention isn't helping the target | abort; revisit intervention design |
| T-Loss fails | intervention regresses target | abort; either intervention is wrong-shaped or item selection in target is unrepresentative |
| O-Loss-per-cat fails (any cat ≥ 2 losses) | intervention causes concentrated off-target regression | abort; this is exactly the PR #77 failure mode caught at $0.08 instead of $2 |
| O-Loss-aggregate fails (total > 2) | broad off-target damage | abort; layering problem (cf. ADR 0138 structural finding) |
| A-Net fails (net ≤ -1) | wins/losses sum negative | abort; intervention is net-harmful even before noise correction |

**Cost analysis** of abort:

- Old protocol abort: $0.05 spike → $2 corpus surprise FAIL = $2.05 to find out
- New protocol abort: $0.08 stratified spike, abort, no corpus = $0.08 to find out

The 25× cost savings is the operational case for the refined protocol.

---

## Section 3 — Comparison-script template

The spike-result note for any future chip should include a per-category
paired-item table generated by a small Python script. The
[PR #73 spike result](./implicit-preference-spike-result-2026-05-25.md)
has the embryonic version (single-category); the stratified version
extends it to all categories.

**Sketch** (chip authors copy this into `/tmp/`, not shipped):

```python
import json
from collections import defaultdict
from pathlib import Path

def compare_paired(
    pre_graded: Path,    # baseline graded JSONL (e.g. PR #70)
    post_graded: Path,   # spike graded JSONL
) -> dict[str, dict[str, int]]:
    """Per-category paired-flip counts."""
    pre = {r["question_id"]: r["is_correct"] for r in load(pre_graded)}
    cats = {r["question_id"]: r["question_type"] for r in load(pre_graded)}

    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {"win": 0, "loss": 0, "rr": 0, "ww": 0}
    )
    for row in load(post_graded):
        qid, post_ok = row["question_id"], row["is_correct"]
        pre_ok = pre.get(qid)
        if pre_ok is None:
            continue
        cat = cats[qid]
        bucket = (
            "rr" if (pre_ok and post_ok)
            else "ww" if (not pre_ok and not post_ok)
            else "win" if (not pre_ok and post_ok)
            else "loss"
        )
        out[cat][bucket] += 1
    return dict(out)

def render_table(counts: dict[str, dict[str, int]]) -> str:
    """Render the per-category | wins | losses | net | table."""
    ...
```

The spike-result note then renders the table and walks each per-category
verdict against the gates in §2.2.

---

## Section 4 — Gate-spec template for future spike charters

Future chips in the ADR-0138 lineage (Option C-i hybrid retrieval, Option
C-ii ingestion-time composition, or any T2.1-class intervention) should
embed a **locked-design gate-spec table** in their charter, analogous to
ADR 0138's locked-design table but specific to the spike protocol they
adopt. Template:

```markdown
## Spike protocol (stratified, per ADR 0140)

| Variable | Choice |
|---|---|
| Sampling | First 4 items per category from `longmemeval_oracle.json`; total n=24 |
| Pre-baseline | PR #70 graded results at `/tmp/.../results-post-t1.5-graded.jsonl` |
| Target category | <e.g. single-session-preference> |
| T-Win | ≥ 1/4 in target |
| T-Loss | 0/4 in target |
| O-Loss-per-cat | ≤ 1 in each of the 5 off-target categories |
| O-Loss-aggregate | total off-target losses ≤ 2 |
| A-Net | net flips across all 24 items ≥ 0 |
| Corpus promotion | spike PASS authorizes 500-item run; corpus gates per PR #76's dual-gate framework |
| Abort | any per-category or aggregate gate fails → revert intervention before corpus run |
```

Per-chip variation is fine (e.g. an intervention targeting two
categories at once might set T-Win on both, or relax O-Loss-per-cat on
one specific category if a known trade-off is being intentionally
accepted). The point is that the table is **locked in the charter**
before the spike runs, so the outcome adjudicates against pre-registered
gates rather than post-hoc rationalization.

---

## Section 5 — Decision tree: which protocol should a chip use?

Not every chip needs the stratified protocol. Use this decision tree:

```
Does the intervention modify a surface that ALL question types route
through (e.g. dialectic prompt, peer-card composition, retrieval layer)?
│
├── YES → stratified protocol (this ADR 0140)
│         Rationale: cross-category collateral damage is the dominant
│         risk; category-localized spike cannot see it.
│         Examples: ADR 0138 (any version), prompt-wording changes,
│         retrieval-layer changes.
│
└── NO → does it modify only a category-specific code path
         (e.g. temporal-only date-extraction helper, an
         answerer setting that only fires for one task shape)?
         │
         ├── YES → category-localized n=30 protocol (legacy, ADR 0138's
         │         original) is fine. The stratified protocol would just
         │         add expensive zeros in non-affected categories.
         │         Examples: a date-parser fix that ONLY runs on
         │         temporal-reasoning items; an SPP-only ablation.
         │
         └── NO (intervention surface unclear)
                 → stratified protocol (default to caution; ambiguous
                 surface means we don't know what the blast radius is)
```

The default is stratified. The category-localized exception is for
interventions whose code path is mechanically isolated to one task
shape and can be shown to not affect other categories' execution.

---

## Section 6 — Cost analysis

| Protocol | Items | Approx cost | Latency | Blast-radius visibility |
|---|---:|---:|---:|---|
| Old category-localized spike (ADR 0138 v1/v2) | 30 in target only | ~$0.05 | ~5 min | target category only |
| **New stratified spike (ADR 0140)** | **24 across 6 categories** | **~$0.05-$0.08** | **~5 min** | **all six categories at n=4** |
| Full corpus sweep | 500 | ~$2 | ~25-60 min | all six categories at native sample size |
| Stratified spike + corpus (PASS path) | 24 + 500 = 524 | ~$2.08 | ~30-65 min | full visibility, two-stage gating |
| Stratified spike alone (FAIL/abort path) | 24 | ~$0.08 | ~5 min | enough to abort without corpus burn |

The stratified spike is roughly the same cost as the category-localized
spike (a few extra items per off-target category; same model). The
operational win is the abort path: the old protocol's FAIL discovery
required $2.05 (spike + corpus); the new protocol's FAIL discovery costs
$0.08.

PR #77's specific cost: $0.05 spike + $2 corpus = $2.05 to discover the
knowledge-update regression. Under the new protocol, the same regression
would have been visible at the spike's per-category off-target table for
$0.08 — savings of $1.97.

This isn't dollar-significant; it's **operationally significant** because
$2 corpus runs gate human-decision-cycle latency on every revert
question. The refined protocol pushes the decision point upstream into a
~5-minute spike.

---

## Section 7 — Honest disclosure: what stratified sampling cannot catch

The refined protocol is materially better than the category-localized
one, but it is not perfect:

1. **Per-category CI is wider at n=4 than n=30.** A single item flip in
   an off-target category is 25% of that category's spike sample.
   Borderline interventions may produce ambiguous spike results
   ("net +1 in target, net -1 in one off-target") that genuinely need
   corpus measurement to adjudicate. The protocol explicitly accepts
   this — see Abort criterion's "ambiguous + cheap corpus" path. It is
   strictly better than the old protocol's "category PASS, corpus
   surprise FAIL," but it does not eliminate corpus runs.

2. **Item-selection bias is now category-correlated.** Picking the first
   4 items per category from the oracle JSONL anchors the spike to a
   specific sub-sample. If those 4 items happen to be unusually
   easy/hard within their category, the spike's per-category baseline is
   off. The deterministic-order choice is intentional (cross-chip
   comparability) but it carries this risk. Future protocol refinements
   could rotate the sample slice (items 0-3, 4-7, etc.) across chips in
   the same lineage to spot-check.

3. **Within-category collateral on the unmeasured (5-N)/N items is
   invisible.** With n=4 per category at corpus size 78 (knowledge-update),
   the spike sees 4/78 = 5% of that category. The other 74 items'
   behavior is unmeasured. The refined protocol's per-category gate
   catches *concentrated* regressions but not *broad-but-shallow*
   ones at sub-spike-resolution. The aggregate A-Net gate is the
   second-order check, but it's still aggregating at n=24 total.

4. **The protocol does not address judge-determinism issues.**
   gpt-4o-mini grading variance was a small-but-real factor in PR #76
   vs PR #77's per-item disagreement (cf. PR #77's "honest disclosure"
   bullet on judge-disagreement spot-checks). The stratified protocol
   inherits this; addressing it would require a re-grade pass on the
   same hypotheses, which is a separate methodology question.

5. **The PR #77 finding that single-global-peer-card serves six task
   shapes is structural.** Any intervention at that layer faces the
   layering problem regardless of which spike protocol measures it.
   The protocol can detect the problem cheaply; it cannot solve it.

Items 1-3 are accepted protocol design trade-offs. Items 4-5 are
out-of-scope for this chip but are noted so future chips don't expect
the protocol to address them.

---

## Section 8 — Promotion gate for ADR 0140 itself

ADR 0140 ships as **Proposed**. It flips to **Accepted** when:

- ≥ 2 chips in the ADR-0138 lineage (or any prompt/adapter/retrieval
  layer change) have adopted the stratified protocol from charter
  through spike-result, AND
- those chips' corpus measurements have **validated the spike's
  PASS/FAIL verdict** — i.e. no spike PASS that the corpus then
  contradicts (false-negative protocol failure), and no spike FAIL that
  a subsequent forced corpus run shows was actually fine
  (false-positive protocol failure).

Until those two data points are collected, ADR 0140 is a methodology
proposal with PR #77's failure as motivation but no positive validation.
Future chips that adopt it should explicitly note "first/second adopter
of ADR 0140" in their charter, so the promotion gate is auditable.

---

## References

- [`longmemeval-baseline-post-pr75-2026-05-25.md`](./longmemeval-baseline-post-pr75-2026-05-25.md)
  — PR #77 corpus sweep that motivated this chip.
- [`implicit-preference-spike-result-2026-05-25.md`](./implicit-preference-spike-result-2026-05-25.md)
  — PR #73 spike v1 (Gate B FAIL, broad regressions).
- [`implicit-preference-respike-result-2026-05-25.md`](./implicit-preference-respike-result-2026-05-25.md)
  — PR #76 spike v2 (Gate B FAIL by 1, framing later falsified at corpus).
- [`implicit-preference-inference-2026-05-25.md`](./implicit-preference-inference-2026-05-25.md)
  — ADR 0138's diagnostic note (original Gate A/B framework lives here).
- [ADR 0138 — Implicit Preference Inference](../../docs/adr/0138-implicit-preference-inference.md).
- [ADR 0140 — Stratified Spike Protocol](../../docs/adr/0140-stratified-spike-protocol.md)
  (this chip's locked-design output).
- [PR #77](https://github.com/elementalcollision/chimera/pull/77) — the
  corpus-FAIL evidence that catalysed this protocol refinement.
