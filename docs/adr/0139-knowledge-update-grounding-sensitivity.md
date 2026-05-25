# ADR 0139 — Knowledge-Update Grounding Sensitivity (diagnostic)

**Status**: Proposed (2026-05-25)

> Diagnostic-only chip. Inspects the four knowledge-update items that flipped right→wrong under PR #75's `## User context` heuristic (PR #77's largest single category drag). **The presumed mechanism — knowledge-update sensitivity to peer-card layering — is falsified.** All four lost items had byte-identical prompts between the PR #70 and PR #75 baselines; the hypothesis differences are pure o4-mini stochastic re-roll variance. No intervention chartered. No code shipped. Captures the methodology lesson for future spikes.

## Context

[ADR 0138](./0138-implicit-preference-inference.md) shipped a diagnostic-only investigation that recommended Option B (adapter grounding extension) conditional on a spike. PR #72 / PR #75 implemented two designs in that family; PR #77's corpus baseline [`longmemeval-baseline-post-pr75-2026-05-25.md`](../../mind/research/longmemeval-baseline-post-pr75-2026-05-25.md) declared the FAIL verdict and recommended revert.

PR #77's per-category breakdown showed **knowledge-update −5.13pp (4 items right→wrong, 0 wins)** as the dominant regression cause. PR #77 attributed this to PR #75's `## User context` section "crowd[ing] out signal the model needs from the conversation history about factual updates the user reported" — a layering effect specific to the knowledge-update task shape. PR #77 explicitly deferred per-item inspection: *"the four lost items should be inspected before any future SPP intervention (not in scope of this chip)."*

This ADR captures the result of that inspection. The companion research note [`knowledge-update-layering-2026-05-25.md`](../../mind/research/knowledge-update-layering-2026-05-25.md) carries the full per-item table, the heuristic-firing audit script, and the cross-category replication.

## Diagnostic outcome (from the companion research note)

| Audit | Result |
|---|---|
| PR #75 heuristic re-applied to the 4 lost items | **0 bullets emitted on all 4** — `## User context` section omitted |
| Code-path divergence between PR #70 and PR #75 baselines on these 4 items | **None** — prompts are byte-identical |
| Hypothesis differences | Pure o4-mini stochastic re-roll variance on identical context |
| Cross-category replication (heuristic-firing audit, n=500) | **All −7 net losses across categories** sit in the not-fired pool (byte-identical prompts) |
| Effect decomposition | Heuristic-fired bucket (n=126): **+2 net** (3w/1l). Not-fired bucket (n=374): **−6 net** (7w/13l, churn 5.3%) |

The presumed knowledge-update layering mechanism is falsified: the heuristic did not change the prompt on any of the four lost items.

## Finding

**Knowledge-update is not structurally sensitive to peer-card additions.** Its four corpus-level "losses" under PR #75 were o4-mini stochastic re-rolls on byte-identical prompts. The same audit shows PR #75's heuristic, restricted to items where it actually fired, has a **+2 net** effect across all categories — small enough to sit inside the same stochasticity envelope that produced the −6 not-fired-bucket re-roll.

## Mechanism statement (falsifiable)

> The LongMemEval corpus at n=500 with `openai/o4-mini` as the answerer carries approximately 5% per-item run-to-run stochastic churn on byte-identical prompts. A single full-sweep delta of ±5–10 items (±1.0–2.0pp overall) is indistinguishable from a re-roll unless decomposed by whether the intervention actually changed the prompt for each item.

A future controlled study can falsify this by running PR #75's commit twice on the same dataset, model, and code; if the second run reproduces PR #77's per-category deltas, the stochasticity floor estimate is wrong and category-specific sensitivity returns to the table.

## Out-of-scope for this ADR

| Item | Why out of scope |
|---|---|
| Any intervention (heuristic redesign, retrieval, ingestion-time composition) | Diagnostic-only; ADR 0138 already recommends Option C and that path stands |
| Any global solution at the prompt+adapter layer | PR #77's strict-gate revert closed that path; this ADR does not re-open it |
| Variance estimation via repeat sweeps | Would cost ~$2 and ~30 min; valuable but outside the 3-file scope of this chip |
| Per-category heuristic-fired sample sizes (knowledge-update n=19 fired) | Too small for per-category effect estimates on their own; would require larger sweeps |

## Forward path candidates (informed, not chartered)

- **ADR 0138 Option C-ii — ingestion-time category-aware peer-card composition.** This finding weakens (not eliminates) the case for C-ii: the original motivation was a knowledge-update sensitivity claim that no longer holds. Any future C-ii design needs a different justification — e.g. fired-bucket measurement showing differential effect across categories *where the heuristic actually fires*, with per-category n large enough to discriminate from the ~3% fired-bucket churn floor.
- **ADR 0138 Option C-retrieval / ADR 0134 Phase 4 #6.b hybrid retrieval.** Sidesteps the prompt-layer engagement entirely. Independent of this finding; stands on its own.
- **Knowledge-update specific bullet exclusion in any future User context section.** No longer load-bearing — the heuristic does not fire on knowledge-update items in any pattern this audit detected.

## Methodology consequence

Future LongMemEval corpus sweeps comparing adapter heuristics MUST report the **fired-vs-not-fired flip table** alongside the per-category delta:

| Bucket | Definition | Why required |
|---|---|---|
| Fired | Items where the new heuristic emitted non-empty output | The only items whose prompts actually changed; the proper denominator for measuring heuristic effect |
| Not-fired | Items where the new heuristic emitted nothing | Byte-identical prompts to the baseline; stochasticity floor for the run |

Without this decomposition, an adapter intervention that touches ~25% of items will have its effect estimate dominated by the stochastic re-roll noise of the untouched 75%, exactly as happened with PR #75's measurement.

Per-bucket churn (this run): **3.2% fired, 5.3% not-fired**. Any claimed heuristic effect smaller than the not-fired noise band cannot be attributed to the heuristic from a single corpus sweep — a variance estimate (repeat sweep at fixed commit) is required to discriminate.

[ADR 0140](./0140-stratified-spike-protocol.md) (sibling chip, stratified spike protocol) addresses the *spike-vs-corpus* methodology gap. This ADR addresses the *corpus-attribution* methodology gap. The two are complementary.

## Status

**Proposed.** Diagnostic-only; no intervention chartered. Companion note: [`mind/research/knowledge-update-layering-2026-05-25.md`](../../mind/research/knowledge-update-layering-2026-05-25.md).

## References

- [ADR 0138 — Implicit Preference Inference](./0138-implicit-preference-inference.md) — parent ADR. Option C-ii's category-sensitivity premise is weakened by this finding; Option C-retrieval stands.
- [ADR 0140 — Stratified Spike Protocol](./0140-stratified-spike-protocol.md) — sibling chip, addresses spike-vs-corpus gap; this ADR addresses corpus-attribution gap.
- [`longmemeval-baseline-post-pr75-2026-05-25.md`](../../mind/research/longmemeval-baseline-post-pr75-2026-05-25.md) — PR #77, the corpus FAIL baseline whose per-category attribution this ADR re-attributes.
- [`temporal-reasoning-regression-2026-05-25.md`](../../mind/research/temporal-reasoning-regression-2026-05-25.md) — PR #68, methodology template.
- PR #75 heuristic source: `git show 3278f31 -- chimera/evals/longmemeval.py` (reverted on `main`).
