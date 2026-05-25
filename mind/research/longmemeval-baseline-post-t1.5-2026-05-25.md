# LongMemEval baseline — post-T1.5 full sweep (2026-05-25)

**Purpose**: Falsifying experiment for PR #69's path-2 hypothesis — *"does adding absolute date anchors to the dialectic grounding alone close the temporal-reasoning regression, or is hybrid retrieval (T2.1) actually required?"*

Companion to [`longmemeval-baseline-2026-05-25.md`](./longmemeval-baseline-2026-05-25.md) (the post-Tier-1 full-sweep baseline at `7e379ae` — 80.60% overall, 53.38% temporal-reasoning). This note carries the load-bearing numbers going forward; the post-T1.4 note stays as historical record.

---

## Headline scores

**Full sweep, 500 items, `longmemeval_oracle.json`, post-T1.5 (`main` at `14192658`).**

| Category | Total | Correct | Accuracy |
|---|---:|---:|---:|
| knowledge-update | 78 | 75 | 96.15% |
| multi-session | 133 | 120 | 90.23% |
| single-session-assistant | 56 | 56 | 100.00% |
| single-session-preference | 30 | 14 | 46.67% |
| single-session-user | 70 | 69 | 98.57% |
| temporal-reasoning | 133 | 120 | 90.23% |
| | | | |
| **overall** | **500** | **454** | **90.80%** |

### Side-by-side with post-T1.4 (`7e379ae`)

| Category | Post-T1.4 (PR #67) | Post-T1.5 (this sweep) | Δ |
|---|---:|---:|---:|
| knowledge-update | 93.59% (73/78) | **96.15%** (75/78) | **+2.56pp** |
| multi-session | 90.98% (121/133) | 90.23% (120/133) | −0.75pp |
| single-session-assistant | 98.21% (55/56) | **100.00%** (56/56) | **+1.79pp** |
| single-session-preference | 50.00% (15/30) | 46.67% (14/30) | −3.33pp |
| single-session-user | 97.14% (68/70) | **98.57%** (69/70) | **+1.43pp** |
| temporal-reasoning | 53.38% (71/133) | **90.23%** (120/133) | **+36.85pp** |
| **overall** | **80.60%** (403/500) | **90.80%** (454/500) | **+10.20pp** |

> **Noise floor caveat (PR #67's lesson).** single-session-preference at n=30 is the smallest category; the −3.33pp move (15/30 → 14/30) is a one-item flip and below the n=30 sampling-noise floor. multi-session at n=133 with a −0.75pp single-item move is also noise. The +36.85pp temporal-reasoning move at n=133 is far outside any sampling-noise envelope and is the real signal.

---

## Delta from post-T1.4 — what the grounding extension did

PR #69 added two content shapes to the dialectic surface (no `_DIALECTIC_PROMPT` change):

1. `**Today's date:** {question_date}` above `## History` on the synthetic self peer-card.
2. `**Session date:** {haystack_date}` under each `### Session i` header (both on the self card and the per-session scratch markdown).

**Per-category effect:**

| Failure mode (PR #68 taxonomy on 62 post-T1.4 misses) | Hypothesis | Observed after T1.5 |
|---|---|---|
| **B1 hedged-ignorance** (*"I don't have dates"*) — was 53.2% (33/62) of temporal misses | Adding absolute dates to grounding should collapse this class | **6/133 = 4.5%** of items still hedge. Class share of misses: 6/13 = 46.2% — *share* held but *absolute count* dropped ~5.5× |
| **B2 zero-anchor** (*"today = 0 days ago"*) — was 24.2% (15/62) of temporal misses | A real `**Today's date:**` anchor should eliminate this | **1/133 = 0.8%** still zero-anchors (single residual `5e1b23de`: *"You attended the 3-day workshop today—so it was zero months ago"*). Class essentially collapsed |
| **C wrong-value/wrong-topic** — was 22.6% (14/62) of temporal misses | This class is grounding-independent (retrieval / arithmetic errors) | **3/133 = 2.3%** still wrong-value; class is the residual hard core |

The B1+B2 share (77.4% of post-T1.4 temporal misses) was the falsifiable target. **It collapsed.** The residual is dominated by:

- **B1 surviving (6 items)** — items where the gold answer requires duration *spent* on an activity (e.g. *"how many days did I spend on my camping trip"*, *"how many weeks did I spend reading X"*). The session-level date headers anchor *when* a session occurred but not *how long an activity within it lasted*; the model honestly hedges. This is a content-shape gap one layer deeper than the chip addressed.
- **C wrong-value (3 items)** — `370a8ff4` (got both dates right but arithmetic wrong: 81 days → "11.5 weeks" vs gold 15); `gpt4_8e165409` (wrong session date picked: 22 days vs gold 14); `gpt4_59149c78` (wrong retrieval: MoMA vs gold Met). One arithmetic, one date-picking, one non-temporal retrieval — no common cause.
- **2 likely judge false-negatives** (`08f4fc43`: *"Thirty days elapsed"* vs gold *"30 days. 31 days also acceptable"* — judged wrong; `gpt4_e072b769`: *"just under three weeks"* vs gold *"3 weeks ago"* — judged wrong). gpt-4o-mini's strict literal matching on equivalent answers; treating these as ground-truth errors would put the headline at 91.20% (456/500) and temporal-reasoning at 91.73% (122/133).

### Cross-category — non-temporal moves

All non-temporal categories landed within noise. The grounding addition is **functionally inert** outside temporal-reasoning: dates in headers don't change how the model handles a single-session preference rubric or a knowledge-update item. The +2.56pp on knowledge-update (73/78 → 75/78) is two items flipping; the +1.79pp on single-session-assistant is one item flipping. No category regressed by more than a single item.

### Empty-hypothesis count — held steady

| Sweep | Total | Empty hypotheses | Rate |
|---|---:|---:|---:|
| Post-T1.4 (`7e379ae`, 2026-05-25) | 500 | 2 | 0.40% |
| Post-T1.5 (`14192658`, 2026-05-25) | 500 | **3** | **0.60%** |

Three empties: 2 single-session-preference (deep-history items, `2048` budget still tight), 1 temporal-reasoning (`9a707b81`). Not a regression — variance on a small absolute count. T1.1's `max_tokens=2048` default is still doing its job.

---

## Sweep metadata

- **Date of sweep**: 2026-05-25 (UTC)
- **Upstream LongMemEval commit**: `9e0b455f4ef0e2ab8f2e582289761153549043fc` (`/Users/dave/Claude_Primary/LongMemEval`)
- **Chimera commit**: `14192658bd4cf66f4ca97b33ef753e23ef654b6c` (`main` after PR #69)
- **Dataset**: `longmemeval_oracle.json` (500 items, full oracle distribution — no `--n-per-category` cap)
- **Answerer model**: `openai/o4-mini` via OpenRouter
- **Answer max-tokens**: 2048 (T1.1 default per [PR #61](https://github.com/elementalcollision/chimera/pull/61))
- **Judge model**: `openai/gpt-4o-mini` via OpenRouter (same as PR #67 baseline; o4-mini judging-budget issue from PR #56 unchanged)
- **Adapter hypothesis count**: 500/500 (no error rows); 497/500 non-empty hypotheses (3 empties, all graded incorrect)
- **Wall-clock**: sweep ~54 min (sequential o4-mini answer calls, 10:36–11:30); grading ~9 min (sequential gpt-4o-mini calls, 11:30–11:39)
- **Inference cost (rough)**: ~$1.5–2 Chimera-side + ~$0.10 judge-side ≈ **~$2 total**, in line with the PR #57 / PR #67 envelope.

---

## Promotion-gate verdict

Both ADR 0136 grounding-extension gates (from PR #68's recommendation):

| Gate | Bar | Observed | Verdict |
|---|---:|---:|---|
| temporal-reasoning ≥68% | +15pp from 53.38% | **90.23%** (+36.85pp) | **CLEARED** (by 22.23pp) |
| overall ≥80% (no regression) | ≥80.60% | **90.80%** (+10.20pp) | **CLEARED** |

**Path-2 hypothesis (PR #68 §"Recommendation"): CONFIRMED.** Adding absolute date anchors to the grounding alone closed the temporal-reasoning regression. The cross-session-integration sentence in ADR 0136 worked correctly when dates were present in source; supplying the dates was the missing half.

### What this implies for the roadmap

- **T2.1 (Phase 4 #6.b hybrid retrieval) defers indefinitely** per PR #68's load-bearing decision criterion. The 22.6% mode-C residual from PR #68 didn't grow — it shrank in absolute terms (14 → 3 items). Vector retrieval was a hedge against a hypothesis the data now falsifies: the cliff was content-shape, not retrieval-mechanism.
- **Next chartered chip — recommendation**: Tier-2B *implicit preference inference* (PR #67's note already flagged single-session-preference's stuck 50% floor — now 46.67%, the only category not clearing 75%). The 16 remaining preference misses look like they require inferring preferences from prior behaviour, not honoring stated rubrics; that's substantively different from T1.3's one-sentence amend.
- **Alternative — finer-grained grounding chip**: the 6 surviving B1 misses cluster on *activity-duration* questions where session-level dates don't suffice. Could try surfacing `**Activity span:** {first_mention} → {last_mention}` heuristics into the scratch markdown. Smaller payoff envelope (n≤6 for the gain) but the chip is one-day-effort.
- **No new gates from this note** — 90.80% becomes the new regression floor for subsequent chips.

### Charter discipline reminders for the next chip

- The +36.85pp move is the second large-headline win in two consecutive chips (T1.2: +70.98pp / +73.59pp; T1.5: +36.85pp). The next chip should NOT chase another headline jump — at 90.80% overall the per-category n=20–30 noise floor will dominate any non-trivial prompt or grounding amend. Pick a target with clear residual taxonomy (preference floor or activity-duration B1 subclass).
- Honest disclosure: if the next sweep regresses any category by >3pp the chip rolls back. PR #41 / PR #67 / PR #68's compounded lesson — *one* falsifiable measurement at a time, no scope creep.

---

## ADR status

- **[ADR 0136](../../docs/adr/0136-temporal-aware-dialectic.md)** — amended in this PR with a "Promotion gate cleared" note inside the existing `2026-05-25 — grounding extension` subsection. No status change (already `Accepted` from PR #67's promotion).
- **[ADR 0137](../../docs/adr/0137-preference-aware-dialectic.md)** — unchanged; T1.3's chip is unaffected by T1.5 and single-session-preference's −3.33pp move is below the n=30 noise floor.
- **No new ADRs** opened.

---

## Reproduction

```bash
# 1. Sweep (~54 min)
chimera evals longmemeval \
  --items /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  --answer \
  --answer-model openai/o4-mini \
  --answer-max-tokens 2048 \
  --out /tmp/chimera-baseline-t15/results-post-t1.5.jsonl \
  --mind-dir /tmp/chimera-baseline-t15/mind

# 2. Grade (~9 min)
python /tmp/chimera-baseline/grade.py \
  /tmp/chimera-baseline-t15/results-post-t1.5.jsonl \
  /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \
  /tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl \
  openai/gpt-4o-mini

# 3. Aggregate
python -c "
from pathlib import Path
from chimera.evals.longmemeval import summarize_results, format_summary_table
print(format_summary_table(summarize_results(
    Path('/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl'))))
"
```

`grade.py` is unchanged from PR #67's reproduction block (judge prompt verbatim from upstream `evaluate_qa.py`).

### Plumbing sanity check (live grounding presence)

```bash
$ head -3 /tmp/chimera-baseline-t15/mind/peers/self.md
# Peer card — self

**Today's date:** 2023/08/18 (Fri) 04:17

$ grep -c '\*\*Session date:\*\*' /tmp/chimera-baseline-t15/mind/peers/self.md
2   # (matches `**Session date:**` headers, one per `### Session i`)
```

Both `**Today's date:**` and `**Session date:**` are present on the synthetic self-card the answerer reads — PR #69's plumbing is live during this sweep.

---

## References

- [`longmemeval-baseline-2026-05-25.md`](./longmemeval-baseline-2026-05-25.md) — post-Tier-1 full-sweep baseline (`7e379ae`, 80.60% / 53.38% temporal).
- [`temporal-reasoning-regression-2026-05-25.md`](./temporal-reasoning-regression-2026-05-25.md) — PR #68's failure-mode taxonomy; this sweep is the falsifying experiment for its path-2 hypothesis.
- [`timestamp-grounding-design-2026-05-25.md`](./timestamp-grounding-design-2026-05-25.md) — PR #69's design note.
- [ADR 0136 — Temporal-Aware Dialectic](../../docs/adr/0136-temporal-aware-dialectic.md) (amended by this PR with the cleared-gate note).
- PR #67 — post-Tier-1 baseline.
- PR #68 — regression investigation (no code shipped; the grounding-vs-wording diagnosis).
- PR #69 — T1.5: timestamp grounding (the chip this sweep measures).
- Upstream: https://github.com/xiaowu0162/LongMemEval
