# LongMemEval baseline — post-PR #75 full sweep (2026-05-25)

**Purpose**: Pre-registered falsifying experiment for PR #76's Path 3 — *"does PR #75's redesigned implicit-preference heuristic preserve the +6.67pp SPP gain at corpus scale without regressing overall accuracy below the PR #70 floor?"*

Companion to [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) (the post-T1.5 baseline at `14192658` — 90.80% overall, the regression floor this chip had to clear). PR #76's [respike note](./implicit-preference-respike-result-2026-05-25.md) recommended this corpus run as the load-bearing measurement to convert ambiguous n=30 spike evidence (3 wins / 1 known-outlier loss; McNemar p≈0.32) into n=500 signal.

---

## Headline scores

**Full sweep, 500 items, `longmemeval_oracle.json`, post-PR #75 (`main` at `a49df61`).**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 78 | 71 | 91.03% |
| multi-session | 133 | 118 | 88.72% |
| single-session-assistant | 56 | 56 | 100.00% |
| single-session-preference | 30 | 17 | 56.67% |
| single-session-user | 70 | 68 | 97.14% |
| temporal-reasoning | 133 | 120 | 90.23% |
| | | | |
| **overall** | **500** | **450** | **90.00%** |

### Side-by-side with post-T1.5 (`14192658`, PR #70 baseline)

| Category | Post-T1.5 (PR #70) | Post-PR #75 (this sweep) | Δ |
|---|---:|---:|---:|
| knowledge-update | 96.15% (75/78) | 91.03% (71/78) | **−5.13pp** |
| multi-session | 90.23% (120/133) | 88.72% (118/133) | −1.50pp |
| single-session-assistant | 100.00% (56/56) | 100.00% (56/56) | 0.00pp |
| single-session-preference | 46.67% (14/30) | **56.67% (17/30)** | **+10.00pp** |
| single-session-user | 98.57% (69/70) | 97.14% (68/70) | −1.43pp |
| temporal-reasoning | 90.23% (120/133) | 90.23% (120/133) | 0.00pp |
| **overall** | **90.80% (454/500)** | **90.00% (450/500)** | **−0.80pp** |

> **Noise-floor caveat.** Per-category n varies (30–133); a single-item flip at n=30 is ±3.33pp, at n=70 is ±1.43pp, at n=133 is ±0.75pp. The single-session-user −1.43pp (1 item) and multi-session −1.50pp (2 items) sit at or just above their per-category noise floors. The knowledge-update −5.13pp (4 items at n=78, ±1.28pp/item) and the SPP +10.00pp (3 items at n=30, ±3.33pp/item) are well outside noise.

---

## Promotion-gate verdict

Pre-registered from PR #76's [Path 3 charter](./implicit-preference-respike-result-2026-05-25.md). **Both** thresholds must be cleared:

| Gate | Bar | Observed | Verdict |
|---|---:|---:|---|
| overall ≥ 90.80% (PR #70 floor) | 90.80% | 90.00% (−0.80pp, −4 items) | **FAIL** |
| single-session-preference ≥ 50.00% | 50.00% | 56.67% (+6.67pp, +2 items above bar) | PASS |

**Verdict: FAIL.** The redesigned heuristic delivered the SPP gain — actually *exceeding* the spike's predicted +6.67pp by another 3.33pp — but the corpus sweep surfaced **collateral damage outside SPP that the n=30 SPP-only spike could not measure**. The strict reading per the charter mandates revert.

---

## Delta from PR #70 — per-category flip table

Item-level flips computed against PR #70's graded `results-post-t1.5-graded.jsonl`:

| Category | wins (✗→✓) | losses (✓→✗) | both right | both wrong | net |
|---|---:|---:|---:|---:|---:|
| knowledge-update | 0 | 4 | 71 | 3 | **−4** |
| multi-session | 3 | 5 | 115 | 10 | −2 |
| single-session-assistant | 0 | 0 | 56 | 0 | 0 |
| single-session-preference | 3 | 0 | 14 | 13 | **+3** |
| single-session-user | 0 | 1 | 68 | 1 | −1 |
| temporal-reasoning | 4 | 4 | 116 | 9 | 0 |
| **TOTAL** | **10** | **14** | **440** | **36** | **−4** |

**Where the regression came from**:

- **knowledge-update (4 losses, 0 wins)** — the largest concentrated regression. PR #75's heuristic surfaces `## User context` above `## History`; for knowledge-update items the user-context section appears to crowd out signal the model needs from the conversation history about *factual updates* the user reported.
- **multi-session (3 wins / 5 losses, net −2)** — high churn (8 items flipped). The `## User context` section presumably reorders prominence for cross-session questions in both helpful and harmful ways depending on whether the relevant fact is preference-shaped or assistant-fact-shaped.
- **single-session-user (1 loss)** — single-item noise but in the loss direction.
- **temporal-reasoning (4 wins / 4 losses, net 0)** — high churn (8 items), zero net. Pure stochasticity from the prominence-reorder, unrelated to the chip's hypothesis.
- **SPP (3 wins / 0 losses)** — the target effect. Items `75f70248`, `95228167`, `d24813b1` flipped right; no SPP item regressed.

The 24 total flips (10 wins + 14 losses) against 476 stable items (440 right-both + 36 wrong-both) confirm the redesign is **active** — it changes behavior on ~5% of items — but the change is net-negative outside the targeted category.

---

## n=30 spike vs n=500 corpus alignment

The spike (PR #76's `respike.graded.jsonl`, 30 SPP-only items against PR #70) showed 4 wins / 1 loss, net +3. The corpus shows 3 wins / 0 losses, net +3. **Net SPP signal direction and magnitude agree.** But the *per-item attribution* diverges substantially:

| Spike (n=30, PR #76) | Corpus (n=500 SPP=30, this sweep) | Same |
|---|---|---|
| Wins: 6b7dfb22, 75832dbd, d24813b1, 95228167† | Wins: 75f70248, 95228167, d24813b1 | Agree: d24813b1, 95228167 |
| Losses: d6233ab6 ("known outlier") | Losses: (none) | — |

† `95228167` was actually wrong in spike too on re-inspection of the artifact; only 3 wins / 1 loss net.

**Five SPP items flipped differently between the two runs** (`6b7dfb22`, `75832dbd`, `75f70248`, `d6233ab6`, and the d24813b1/95228167 stable wins). Specifically:

- **`6b7dfb22`, `75832dbd`** — spike wins that flipped back to wrong at corpus
- **`75f70248`** — corpus win not seen in spike
- **`d6233ab6`** — spike's lone "known-outlier" loss is correct at corpus; the outlier framing didn't replicate

Only **one item (`d24813b1`)** flipped reliably across both runs. The remaining "wins" and the "loss" are run-to-run o4-mini stochastic variance, not stable per-item attributions.

**Methodology lesson.** The spike methodology directionally validated (both runs show SPP +3 net) but per-item gate-tracking at n=30 carries enough stochasticity that Gate A / Gate B counts are not portable to corpus. The Gate B framing in PR #76 (failing by exactly 1 = d6233ab6) was load-bearing on a single non-reproducing flip. The corpus result confirms the charter's premise — *that the spike couldn't adjudicate signal vs noise* — by showing the spike's exact per-item outcomes were not reproducible. The Path 3 corpus sweep was the right falsifying step.

**Critically, the corpus surfaced what the SPP-only spike could not see**: the regressions in knowledge-update, multi-session, and single-session-user. Those four categories were not in the spike's measurement set. The −4 net items overall is dominated by knowledge-update (−4 alone), which the spike literally couldn't observe.

---

## Empty-hypothesis count

| Sweep | Total | Empty hypotheses | Rate |
|---|---:|---:|---:|
| Post-T1.5 (`14192658`, PR #70) | 500 | 3 | 0.60% |
| Post-PR #75 (`a49df61`, this sweep) | 500 | 4 | 0.80% |

One additional empty (4 vs 3) — well within absolute-count variance on a half-percent rate. Not a regression. T1.1's `max_tokens=2048` default holds.

---

## Sweep metadata

- **Date of sweep**: 2026-05-25 (UTC)
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc` (`/Users/dave/Claude_Primary/LongMemEval`)
- **Chimera commit**: `a49df615212e2a7969e08749dc8082c61f622acd` (`main` after PR #76)
- **Dataset**: `longmemeval_oracle.json` (500 items, full oracle distribution)
- **Answerer model**: `openai/o4-mini` via OpenRouter
- **Answer max-tokens**: 2048 (T1.1 default)
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter
- **Adapter hypothesis count**: 500/500 (no error rows); 496/500 non-empty hypotheses (4 empties, all graded incorrect)
- **Wall-clock**: sweep ~25 min (sequential o4-mini answer calls — faster than PR #70's ~54 min, likely OpenRouter capacity); grading ~5 min (sequential gpt-4o-mini calls)
- **Inference cost (rough)**: ~$1.5–2 chimera-side + ~$0.10 judge-side ≈ **~$2 total**, in line with PR #67 / PR #70 envelope.

---

## Recommendation

**Path: revert PR #75 (`3278f31`); declare implicit-preference inference out-of-reach at the prompt+adapter engineering layer.** This PR ships two commits:

1. **This baseline note** (corpus evidence for the FAIL verdict).
2. **`git revert 3278f31`** — restoring `main` to PR #76's state (the diagnostic-only stack at PR #70 + the ADR 0138 Proposed status).

ADR 0138 stays **Proposed**. The diagnostic-only ADR's recommendation table (Option A / B / C) now has corpus evidence falsifying Option B at production scale; the recommended next step is **Option C** — pivot to retrieval-mechanism (Phase 4 #6.b hybrid retrieval) or ingestion-time peer-card composition, both of which are tracked as future chips and require independent design before any code lands.

### Why Option B is now closed at this layer

The PR #72 → #74 revert / PR #75 respike / this Path 3 sweep cycle has falsified the *adapter-grounding-extension family* for implicit preferences. Both filter shapes (PR #72's noisy regex; PR #75's tightened conditioning) cause net-negative overall accuracy:

| Adapter intervention | SPP delta | Overall delta | Verdict |
|---|---:|---:|---|
| PR #72 (`## User context` v1, noisy) | n/a (Gate B fail, 5 right→wrong) | reverted before corpus measurement | reverted |
| PR #75 (redesigned v2) | **+10.00pp** (corpus) | **−0.80pp** (corpus) | revert (this chip) |

Two independent designs in the same content-shape family produced net-negative overall accuracy. The conclusion isn't "v3 might work" — it's that **the adapter cannot promote implicit-preference signal without changing prominence-for-other-categories in ways the model isn't robust to.** This is a layering problem (one global card serving all six task shapes), not a heuristic-quality problem.

### Concretely after this PR merges

- `main` returns to **90.80% overall, 46.67% SPP** (PR #70 baseline) — the durable release floor.
- ADR 0138 status: **Proposed** (no change; the diagnostic-only chip stands).
- Follow-up chip should propose either: **(C-retrieval)** Phase 4 #6.b hybrid retrieval design ADR that explicitly addresses implicit preference at retrieval time, OR **(C-ingestion)** an ingestion-time peer-card composition design that separates implicit-preference surfacing from the dialectic prompt entirely. Both are net-new design work, not iterations on PR #72/#75.
- No new gate from this note — 90.80% remains the regression floor.

### Charter discipline reminders

- PR #72 → #75 burned two chips on the same content-shape family. The next chip in this lineage should require a **prior n=30 spike that measures more than the target category** (or a charter that mandates corpus measurement before status promotion) to catch collateral damage earlier.
- The Path 3 promotion rule (overall + target both required) worked as designed — it correctly caught a net regression that a target-only gate would have rubber-stamped. Keep the dual-gate pattern for any future heuristic chip.

---

## Honest disclosure

- **knowledge-update −5.13pp** is the largest individual category regression and the proximate cause of the overall failure. The four lost items (vs PR #70) should be inspected before any future SPP intervention to characterize *why* `## User context` prominence harms knowledge-update specifically. This is not done in this chip per scope discipline (1–2 files on PASS, 3–4 on FAIL — note + revert + ADR README amend if needed).
- **temporal-reasoning churn (8 items flipped, net 0)** suggests PR #75's prominence change has noisy effects beyond just SPP-vs-non-SPP. A category that net-zero-changes is fine for the gate but means the chip's effect is *not* localized to its target.
- **Spike-vs-corpus per-item disagreement (5/30 SPP items)** means the spike methodology, while directionally correct on net, is unreliable for per-item gate tracking at n=30. PR #76's Gate B "fail by 1 = known outlier" framing was load-bearing on a non-reproducing flip. Future spikes in this family should not over-interpret single-item gate results.
- **Two corpus-result items deserve judge-disagreement inspection**: the SPP-targeted gain rests on 3 items (`75f70248`, `95228167`, `d24813b1`); none of the three matched the spike's win set fully. A spot-check that gpt-4o-mini graded these consistently across the two runs (rather than the o4-mini answers actually changing) would tighten the conclusion. Not done in this chip; flagged as a low-priority post-mortem item.
- **Wall-clock difference (25 min vs PR #70's 54 min)** is unexplained — same model, same item count, same call shape. Likely OpenRouter-side capacity variation; mentioned for reproduction-fidelity transparency.

---

## Reproduction

```bash
# 1. Sweep (~25 min — varied; PR #70 took 54 min same shape)
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  --answer \
  --answer-model openai/o4-mini \
  --answer-max-tokens 2048 \
  --out /tmp/chimera-baseline-t2b-corpus/results-post-pr75.jsonl

# 2. Grade (~5 min)
python /tmp/chimera-baseline/grade.py \
  /tmp/chimera-baseline-t2b-corpus/results-post-pr75.jsonl \
  /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  /tmp/chimera-baseline-t2b-corpus/results-post-pr75.graded.jsonl \
  openai/gpt-4o-mini

# 3. Aggregate
python -c "
from pathlib import Path
from chimera.evals.longmemeval import summarize_results, format_summary_table
print(format_summary_table(summarize_results(
    Path('/tmp/chimera-baseline-t2b-corpus/results-post-pr75.graded.jsonl'))))
"
```

`grade.py` unchanged from PR #67/#70.

---

## References

- [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) — PR #70's 90.80% baseline (the regression floor this chip had to clear).
- [`implicit-preference-inference-2026-05-25.md`](./implicit-preference-inference-2026-05-25.md) — ADR 0138's diagnostic note (Tier-2B investigation).
- [`implicit-preference-spike-result-2026-05-25.md`](./implicit-preference-spike-result-2026-05-25.md) — PR #72/#73 (v1 spike — Gate B fail, reverted).
- [`implicit-preference-respike-design-2026-05-25.md`](./implicit-preference-respike-design-2026-05-25.md) — PR #75 (redesigned heuristic — landed on `main`, reverted by this chip).
- [`implicit-preference-respike-result-2026-05-25.md`](./implicit-preference-respike-result-2026-05-25.md) — PR #76 (respike result — Gate A pass / Gate B fail by 1; recommended this Path 3 corpus sweep).
- [ADR 0138 — Implicit Preference Inference](../../docs/adr/0138-implicit-preference-inference.md) (stays Proposed; Option B closed at this layer; Option C the recommended forward path).
- Upstream: https://github.com/xiaowu0162/LongMemEval
