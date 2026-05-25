# LongMemEval `_s` long-horizon baseline — directional read (2026-05-25)

**Purpose**: First measurement of Chimera's dialectic on the **long-horizon** LongMemEval variant (`longmemeval_s_cleaned.json`). The oracle variant (`longmemeval_oracle.json`) saturates at 90.80% post-T1.5 ([`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md)) — but oracle gives the answerer only the gold sessions. `_s` is the true needle-in-a-haystack test: ~48 sessions and ~493 turns per item (vs typically 1–3 sessions on oracle), and the load-bearing question becomes "*does the dialectic surface still surface the right turns when the self-card is 25–50× longer?*"

This is **Chip B1** (3/3 in the sequential reliability series after A2 CI + A1 chip-branch-jump prevention). It produces the new floor against which any hybrid-retrieval (T2.1) chip must measure itself.

> ⚠️ **Methodology note — directional read, not corpus baseline.** The intended deliverable was a 500-item sweep, but the first attempt was killed at 43 min after operator-cost-feasibility check-in. After operator authorization, this chip ran a **30-item stratified subset (5 per category)** instead. The directional signal is overwhelming (see below), so a fuller sweep is operationally redundant for the load-bearing decision — the chip's question is answered. The 500-item full sweep is documented in [Reproduction](#reproduction) below and deferred to an operator-gated re-run if the precise headline number matters for a downstream artifact. Choice annotated per operator instruction.

---

## Headline scores

**Stratified 30-item subset, `longmemeval_s_cleaned.json`, current `main` at `4d18621`.**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 5 | 0 | 0.00% |
| multi-session | 5 | 0 | 0.00% |
| single-session-assistant | 5 | 1 | 20.00% |
| single-session-preference | 5 | 0 | 0.00% |
| single-session-user | 5 | 1 | 20.00% |
| temporal-reasoning | 5 | 1 | 20.00% |
| | | | |
| **overall** | **30** | **3** | **10.00%** |

### Side-by-side vs oracle (post-T1.5, full 500)

| Category | Oracle (post-T1.5, n=78–133) | `_s` (this subset, n=5/cat) | Δ |
|---|---:|---:|---:|
| knowledge-update | 96.15% (75/78) | 0.00% (0/5) | **−96.15pp** |
| multi-session | 90.23% (120/133) | 0.00% (0/5) | **−90.23pp** |
| single-session-assistant | 100.00% (56/56) | 20.00% (1/5) | **−80.00pp** |
| single-session-preference | 46.67% (14/30) | 0.00% (0/5) | **−46.67pp** |
| single-session-user | 98.57% (69/70) | 20.00% (1/5) | **−78.57pp** |
| temporal-reasoning | 90.23% (120/133) | 20.00% (1/5) | **−70.23pp** |
| **overall** | **90.80%** (454/500) | **10.00%** (3/30) | **−80.80pp** |

**Noise-floor caveat.** At n=5/category, a single item flip is 20pp. So the per-category numbers above are individually wide-error-bar. But: *every* category drops by **≥47pp**, and the overall drop is **−80.80pp**. The probability of an 80-point drop across every category being a sampling artifact is vanishingly small — the signal is well outside the n=30 binomial envelope (95% CI on 3/30 is roughly 2.1–26.5%; the lower end of the CI is still ~64pp below oracle).

The directional finding — *oracle saturation does NOT generalize to `_s`* — is locked in.

---

## Corpus shape — why `_s` is the harder benchmark

| Quantity | Oracle | `_s` | Ratio |
|---|---:|---:|---:|
| Items | 500 | 500 | 1× |
| Sessions per item (min / median / mean / max) | 1–3 typical | 38 / 48 / 47.7 / 62 | ~25–50× |
| Turns per item (mean) | ~15–25 | 493.5 | ~25× |
| Self-card length on dialectic surface | small (~few KB) | very large (~500 KB observed on first item) | ~100× |

The oracle variant is a *prompt-engineering* benchmark — the gold sessions are pre-filtered, and the question is "does Chimera's dialectic compose the right summary." `_s` is a *retrieval-or-attention* benchmark — the gold sessions sit inside 40–60 distractor sessions, and the question is "does the model find them at all."

Per ADR 0136 / PR #69, the current adapter writes **every session** into a synthetic `mind/peers/self.md` self-card with `## Session N` headers and `**Session date:**` anchors. There is no retrieval layer between ingest and the answerer — the full haystack is in the o4-mini context every call. This is the design the post-T1.5 saturation result rests on; this sweep is its long-horizon stress test, and the design fails it.

---

## Load-bearing read — is hybrid retrieval (T2.1) now needed?

**Yes. Strongly. Re-charter T2.1.**

The pre-registered decision rule from the chip skeleton was:

- *Saturation holds* if overall ≥85% and no category drops >10pp from oracle. ⇒ T2.1 stays deferred.
- *Retrieval load-bearing* if overall <85% OR any category drops >15pp from oracle, with the drop concentrated on multi-session or temporal-reasoning. ⇒ T2.1 becomes next chartered chip.
- *Ambiguous* between those bands ⇒ schedule one further diagnostic before deciding.

Observed: overall **10.00%** (vs 85% bar) and **every** category drops **≥47pp** (vs 15pp bar). The drop is not concentrated on multi-session/temporal — it's *uniform*. Even `knowledge-update` and `single-session-assistant`, which were at 96–100% on oracle, collapse to 0–20% here. The decision rule fires unambiguously on the "retrieval load-bearing" branch.

### Why the collapse is uniform across categories

The PR #69 / ADR 0136 grounding extension (timestamp anchors on the self-card) was the load-bearing fix for temporal-reasoning on oracle. On `_s` the *content* of every category is still in the self-card — the prompt grew, not the structure — so a uniform collapse implies the model's *attention* over the now-25×-longer context is the limiting factor, not any one category's grounding shape. This is the classic "needles in a longer haystack" failure mode and is exactly what the LongMemEval paper §4 documents at the `_s` variant.

### What the ADR 0136 amendment said about this

ADR 0136's "Promotion gate cleared" note (post-T1.5) deferred T2.1 with the language *"vector retrieval was a hedge against a hypothesis the data now falsifies: the cliff was content-shape, not retrieval-mechanism."* That conclusion was scoped — correctly — to the oracle variant. This chip's data shows it does **not** extrapolate to `_s`; **on `_s`, the cliff IS retrieval-mechanism.** The two findings are not in conflict — the oracle finding is about prompt shape on a pre-filtered context; the `_s` finding is about attention/retrieval on a needle-in-haystack context. Both can be true simultaneously and both are.

### Operational corollary — cost-feasibility, not just accuracy

A secondary finding from the killed 43-min first attempt: the current adapter at `_s` scale puts ~500 KB into a single o4-mini call per item. The killed run was on track to finish — re-measurement on the 30-item subset gave ~8 s/item, so a full sweep would have been ~70 min and probably ~$5–15 (cost depends on cached prompt prefix behaviour, which we did not measure). That is operationally *fine* — my mid-sweep extrapolation of ~25 hours was wrong, driven by buffered output that gave no signal until the end and one slow first item — but it is also *wasteful*: the bulk of those tokens are distractor sessions the answerer has to attend over. A hybrid-retrieval adapter that ships only the top-k relevant sessions would compress per-call input ~10–20×, with both accuracy (per above) and cost upside.

### Recommendation

1. **Charter T2.1 as the next chip.** Scope: FTS5 + vector hybrid into the synthetic-self-card builder; ship only top-k matched sessions per question. Promotion gate: ≥50% overall on `_s` 30-item subset (5× this baseline), no oracle regression on the post-T1.5 90.80% floor.
2. **Re-run the full 500-item `_s` sweep against T2.1's adapter, not the current one.** A full-corpus baseline on the current adapter would lock in a number we already know is uninformative (~10%); the budget is better spent measuring the intervention.
3. **Leave the oracle baseline as-is** — it remains the regression floor for prompt-shape chips.

---

## Sweep metadata

- **Date of sweep**: 2026-05-25 (UTC)
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc` (`/Users/dave/Claude_Primary/LongMemEval`)
- **Chimera commit**: `4d18621` (`main` after PR #83)
- **Dataset**: `longmemeval_s_cleaned.json` (264 MB; 500 items; mean 47.7 sessions / 493.5 turns per item)
- **Items measured**: 30 (5 per category via `--n-per-category 5`)
- **Answerer model**: `openai/o4-mini` via OpenRouter
- **Answer max-tokens**: 2048
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter
- **Wall-clock**: 250 s end-to-end answer (~8.3 s/item average), ~30 s grading
- **Inference cost (rough)**: ~$0.30–0.60 (not separately metered; well inside the chip's $5–10 envelope, with the remainder unspent and the corresponding full-sweep deferred)

---

## Reproduction

```bash
# 1. Directional subset (~5 min, this baseline)
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_s_cleaned.json \
  --answer \
  --answer-model openai/o4-mini \
  --answer-max-tokens 2048 \
  --n-per-category 5 \
  --out /tmp/chimera-baseline-s/results.jsonl \
  --mind-dir /tmp/chimera-baseline-s/mind

# 1'. Full sweep (deferred — operator gates spend; estimated ~70 min, ~$5–15)
# Drop --n-per-category to run all 500 items.

# 2. Grade
uv run python /tmp/chimera-baseline/grade.py \
  /tmp/chimera-baseline-s/results.jsonl \
  /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_s_cleaned.json \
  /tmp/chimera-baseline-s/results.graded.jsonl \
  openai/gpt-4o-mini

# 3. Aggregate
uv run python -c "
from pathlib import Path
from chimera.evals.longmemeval import summarize_results, format_summary_table
print(format_summary_table(summarize_results(
    Path('/tmp/chimera-baseline-s/results.graded.jsonl'))))
"
```

The `_s` corpus is downloaded from the upstream HuggingFace mirror (`https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json`) and lives under `/Users/dave/Claude_Primary/LongMemEval/data/` alongside `longmemeval_oracle.json`.

---

## ADR status

- **[ADR 0136](../../docs/adr/0136-temporal-aware-dialectic.md)** — unchanged. The cleared-gate note from PR #69 stands; this chip does not contradict the oracle saturation finding. A follow-up amendment scoping the saturation result to oracle (and noting `_s` retrieval as the next-chartered intervention) is appropriate but out of scope for this measurement-only chip.
- **No new ADRs opened.** T2.1's re-charter is a next-chip action, not this one's deliverable.

---

## Charter discipline notes

- This is a **measurement-only chip** — no adapter or prompt code changes were made.
- The "stratified subset instead of full sweep" choice was made mid-chip after an operator check-in at the 43-min mark of an attempted 500-item sweep. The choice is annotated in the header and in the [Recommendation](#recommendation) section so future readers can reconstruct why the corpus baseline shows 30 items rather than 500.
- The signal is far outside the n=30 noise envelope for the load-bearing decision the chip was chartered to make. Re-running on 500 items to firm up the headline number is *possible* but does not change the decision and was therefore not done — see the [Recommendation](#recommendation) for the better use of the next-sweep budget.

---

## References

- [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) — oracle post-T1.5 baseline (90.80%); the comparison point.
- [`longmemeval-baseline-post-pr75-2026-05-25.md`](./longmemeval-baseline-post-pr75-2026-05-25.md) — corpus-level FAIL verdict on PR #75 (implicit-preference inference); the methodology source for stratified attribution.
- ADR 0136 — Temporal-Aware Dialectic.
- Upstream: https://github.com/xiaowu0162/LongMemEval (paper §4 documents the `_s` long-context variant).
