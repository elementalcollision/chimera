# ADR 0140 — Stratified Spike Protocol

**Status**: Proposed (2026-05-25)

> Methodology ADR. Refines the n=30 category-localized spike protocol
> from [ADR 0138](./0138-implicit-preference-inference.md) by stratifying
> sampling across all six LongMemEval categories and replacing the single
> Gate A/B with per-category gates plus a corpus-promotion criterion.
> No code shipped in this ADR; the helper `stratified_subset` and any
> CLI surfaces are explicitly out-of-scope and tracked as a separate
> chip. Promotion gate to Accepted requires ≥ 2 adopting chips whose
> corpus measurements validate the spike verdict.

## Context

[ADR 0138](./0138-implicit-preference-inference.md) defined the
**category-localized n=30 spike protocol** (Gate A: ≥2 wrong→right in
target category; Gate B: 0 right→wrong in target category). The protocol
was used twice:

- **PR #72→#73 (v1)** — Gate B FAIL (5 right→wrong, broad noise);
  reverted.
- **PR #75→#76 (v2)** — Gate A PASS, Gate B FAIL by 1 (`d6233ab6`,
  framed as a known outlier); recommended a $2 corpus sweep before
  status promotion.

[PR #77](https://github.com/elementalcollision/chimera/pull/77)'s
500-item corpus sweep confirmed the v2 spike's directional SPP gain
(+10.00pp at corpus vs +6.67pp at spike) **but surfaced collateral damage
in three categories the spike could not measure** (knowledge-update
−5.13pp, multi-session −1.50pp, single-session-user −1.43pp; overall
−0.80pp, net −4 items). Per-item reproducibility was poor: only 1/5
spike flips persisted literally at corpus, though the SPP-net direction
agreed.

The cost: $2.05 (spike + corpus) to discover a regression that lived
entirely outside the spike's measurement set. Per PR #77's recommendation
note:

> *"future spikes in this lineage need broader measurement scope or a
> corpus pre-promotion gate."*

This ADR designs that refinement. The full motivation, evidence, and
trade-off discussion is in the companion research note:
[`mind/research/spike-protocol-refinement-2026-05-25.md`](../../mind/research/spike-protocol-refinement-2026-05-25.md).

## Decision

Adopt a **stratified spike protocol with per-category gates and a
corpus-promotion criterion** for future LongMemEval-class interventions
whose surface is not mechanically isolated to one task shape.

### When to use this protocol

| Intervention surface | Protocol |
|---|---|
| Touches a code path that all six LongMemEval question types route through (dialectic prompt, peer-card composition, retrieval, answerer config) | **Stratified protocol (this ADR)** |
| Mechanically isolated to one task shape (e.g. a temporal-only date helper) | Legacy category-localized protocol (ADR 0138) is acceptable |
| Surface unclear / borderline | Default to stratified |

Future chips MUST cite this ADR in their charter when adopting the
stratified protocol and embed a locked-design gate-spec table (template
in §"Locked-design table" below).

## Locked-design table

| Variable | Choice |
|---|---|
| **Sampling** | First `per_category` items per LongMemEval category from `longmemeval_oracle.json`. Default `per_category = 4`; acceptable range `[3, 5]`. Total n ∈ `[18, 30]`. Six categories: `knowledge-update`, `multi-session`, `single-session-assistant`, `single-session-preference`, `single-session-user`, `temporal-reasoning` |
| **Item selection determinism** | Stable oracle-file order; the spike set is identical across chips in the same lineage |
| **Pre-baseline** | Most-recent corpus-graded JSONL on `main` (currently PR #70 / `64d492a`'s post-T1.5 graded results) |
| **Target category** | Each chip's charter names the intervention's intended-help category |
| **Per-target gates** | T-Win: wrong→right in target ≥ `T_win` (default ≥1 at n=4). T-Loss: right→wrong in target ≤ `T_loss` (default 0 at n=4) |
| **Per-off-target gates** | O-Loss-per-cat: right→wrong ≤ 1 in EACH of the 5 off-target categories. O-Loss-aggregate: total off-target right→wrong ≤ 2 |
| **Aggregate gate** | A-Net: net (wins − losses) across all 24 items ≥ 0 |
| **PASS authorizes** | A 500-item corpus run, gated by the dual-gate framework from [ADR 0138 / PR #76 (overall ≥ regression-floor AND target ≥ target-threshold)](./0138-implicit-preference-inference.md). Corpus result remains the actual `main`-merge gate |
| **FAIL (any gate) action** | Abort; do NOT spend corpus budget. Revisit intervention design |
| **Implementation surface** | Use existing `chimera/evals/longmemeval.py::run_batch` `per_category_limit=4` against the oracle JSONL. A dedicated `stratified_subset` helper is desirable but **out-of-scope for this ADR**; tracked as a separate chip |
| **Comparison script** | Each spike-result note includes a per-category paired-item flip table (template in companion research note §3). Chip authors copy the template into `/tmp/`; the analysis script itself is not shipped |
| **Charter requirement** | Adopting chips MUST embed a locked-design gate-spec table in their charter, citing this ADR. Per-chip variation (T_win threshold, O-Loss tolerance) is allowed but must be pre-registered |

## Options considered

### Option A — Keep category-localized n=30 protocol

**Verdict**: Rejected. PR #77 falsified this protocol at corpus scale:
SPP PASS at spike, overall FAIL at corpus, $2 burned. Two independent
chips (PR #73, PR #76) saw the same blind spot. The protocol works for
interventions whose surface is mechanically category-isolated, but
LongMemEval's adapter-level interventions are categorically not.

### Option B — Stratified spike with per-category gates *(chosen)*

**Verdict**: Recommended. Catches the PR #77 failure mode at $0.08
instead of $2.05. Same per-chip cost envelope. Trade-off: per-category
n=4 is wider-CI than n=30 in target, so some interventions will produce
"ambiguous spike, recommend corpus" rather than clean PASS/FAIL. This is
explicitly accepted as a valid outcome (see §"Honest disclosure" in
companion note).

### Option C — Skip spike, run corpus on every intervention

**Verdict**: Rejected. $2 per intervention × N iterations is prohibitive
for design-space exploration. The whole operational case for spikes is
to triage cheap-and-fast before spending the corpus budget. Option C
also doesn't surface the "spike + corpus" two-stage signal that helps
distinguish "intervention works as designed but unexpected collateral"
from "intervention doesn't work."

### Option D — Bayesian / variance-aware analysis on the n=30 spike

**Verdict**: Rejected for now. McNemar's-test framings (briefly raised
in PR #76's meta-note) could quantify "is the per-item signal
statistically distinguishable from noise" but do not address the
category-localized blind spot. A variance-aware analysis on the wrong
sample (target-only) doesn't help; on the right sample (stratified) it
is a useful add-on but not a substitute for the per-category gates. May
revisit as a future protocol amendment.

## Charter-discipline notes

1. **No code shipped here.** This ADR is methodology. `stratified_subset`
   and any related CLI/test changes belong to a separate chip; the
   existing `run_batch(per_category_limit=...)` path is the supported
   MVP for adopting chips.

2. **No change to ADR 0138's historical record.** ADR 0138's locked
   Gate A/B framing stands as the protocol-of-record for PR #72/#75. The
   "Charter rules carried forward" section in ADR 0138 already requires
   broader measurement before status promotion; this ADR formalizes
   *what* "broader" means.

3. **Per-chip variation is allowed but must be pre-registered.** If a
   chip's intervention has a known trade-off (e.g. it intentionally
   trades a 1-item regression in one off-target category for a 3-item
   win in the target), it can relax O-Loss-per-cat for that category
   *in the charter, before the spike runs*. Post-hoc relaxation is
   protocol violation.

4. **Honest disclosure required.** Adopting chips' spike-result notes
   must explicitly call out (a) any gate cleared by exactly the minimum
   threshold (noise-floor adjacent), (b) any per-item flips known to be
   unreliable across runs, (c) any off-target category whose n=4 sample
   may not be representative of that category's behavior.

5. **Two-adopter promotion gate.** ADR 0140 stays Proposed until ≥ 2
   chips have completed a stratified-spike → corpus cycle AND the
   corpus result validated the spike verdict (no false-positive
   abort, no false-negative pass-through). Until then, the protocol is
   a methodology proposal grounded in PR #77's negative result, not a
   positively-validated framework.

## Out of scope

- **Implementation of `stratified_subset`** — separate chip; the
  existing `run_batch(per_category_limit=...)` path is the supported MVP.
- **CLI flag additions** to `chimera evals longmemeval` — separate chip
  if needed.
- **Changes to ADR 0138's historical Gate A/B language** — that ADR's
  protocol is the historical record for PR #72/#75; this ADR is the
  forward path.
- **Re-running PR #75 / PR #76 under the new protocol** — the corpus
  measurement at PR #77 already adjudicated; no value in retroactive
  spike runs.
- **Judge-determinism / re-grading methodology** — separate concern
  (see PR #77's honest disclosure on judge spot-checks).
- **Variance-aware / Bayesian analysis on spike results** — possible
  future protocol amendment; not load-bearing for the current PR #77
  failure mode.
- **Stratified protocols for non-LongMemEval evals** — this ADR is
  scoped to LongMemEval's six-category structure. Other evals may want
  analogous protocols but the specific gate thresholds and category
  list would differ.

## Forward path

The next ADR-0138-Option-C chip — whether C-i (hybrid retrieval at the
dialectic boundary) or C-ii (ingestion-time category-aware peer-card
composition) — should be the **first adopter** of this protocol. The
chip's charter would:

1. Cite this ADR.
2. Embed the locked-design gate-spec table with chip-specific values
   (target category = single-session-preference; T_win = 1; gates per
   §"Locked-design table" defaults).
3. Run the stratified spike before any corpus sweep.
4. If PASS → 500-item corpus run gated by ADR 0138 / PR #76 dual gates.
5. If FAIL → abort, no corpus burn.

After the second adopting chip completes a full spike → corpus cycle
*and* both adopters' corpus results validate their spike verdicts, this
ADR flips to **Accepted**.

## References

- [`mind/research/spike-protocol-refinement-2026-05-25.md`](../../mind/research/spike-protocol-refinement-2026-05-25.md)
  — companion research note; full design rationale, decision tree,
  comparison-script template, cost analysis.
- [ADR 0138 — Implicit Preference Inference](./0138-implicit-preference-inference.md)
  — predecessor protocol (category-localized n=30); diagnostic content
  remains valid; recommended path is now Option C.
- [`mind/research/longmemeval-baseline-post-pr75-2026-05-25.md`](../../mind/research/longmemeval-baseline-post-pr75-2026-05-25.md)
  — PR #77 corpus sweep that catalysed this refinement.
- [`mind/research/implicit-preference-spike-result-2026-05-25.md`](../../mind/research/implicit-preference-spike-result-2026-05-25.md)
  — PR #73 spike v1.
- [`mind/research/implicit-preference-respike-result-2026-05-25.md`](../../mind/research/implicit-preference-respike-result-2026-05-25.md)
  — PR #76 spike v2.
- [PR #77](https://github.com/elementalcollision/chimera/pull/77) —
  corpus-FAIL verdict + spike-vs-corpus disagreement evidence.
