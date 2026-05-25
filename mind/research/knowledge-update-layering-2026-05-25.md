# Knowledge-update layering diagnostic — post-PR #77 follow-up (2026-05-25)

**Purpose**: PR #77's [post-PR #75 corpus baseline](./longmemeval-baseline-post-pr75-2026-05-25.md) attributed the FAIL verdict's largest single drag — **knowledge-update −5.13pp (4 items right→wrong, 0 wins)** — to PR #75's `## User context` peer-card section "layering on" the wrong category. PR #77 explicitly deferred per-item inspection: *"the four lost items should be inspected before any future SPP intervention (not in scope of this chip)."* This note executes that inspection.

**Headline**: the layering hypothesis is **falsified**. All four lost knowledge-update items were on inputs where PR #75's heuristic emitted **zero bullets** — i.e. the assembled prompts were byte-identical to PR #70's. The hypothesis differences are pure o4-mini stochastic re-roll variance on identical context. PR #77's per-category attribution overcounted the heuristic's effect.

---

## The four items

From `/tmp/chimera-baseline-t2b-corpus/results-post-pr75.graded.jsonl` vs `/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl`. All four are knowledge-update; all four flipped right (PR #70) → wrong (PR #75).

| `question_id` | Question (excerpt) | Gold | PR #70 hypothesis (correct) | PR #75 hypothesis (wrong) |
|---|---|---|---|---|
| `830ce83f` | Where did Rachel move to after her recent relocation? | the suburbs | "Rachel's most recent move was out of the city back into the suburbs." | "After her recent move, Rachel relocated to Chicago." |
| `9ea5eabc` | Where did I go on my most recent family trip? | Paris | "You went on your most recent family trip to Paris." | "Your most recent family trip was to Hawaii, where you all went snorkeling…" |
| `c4ea545c` | Do I go to the gym more frequently than I did previously? | Yes | "Yes. In your initial schedule you went to the gym three times a week…, but by your August session you noted you'd been hitting the gym four times weekly…" | "I don't have any record of your earlier gym frequency… Without a clear 'before' frequency, I can't tell if you're working out more now than previously." |
| `69fee5aa` | How many pre-1920 American coins do I have in my collection? | 38 | "You'd previously stated 37, then added a 1915-S Barber quarter, bringing your total to 38." | "You mentioned earlier that your pre-1920 American coin collection comprises 37 coins." |

A reader scanning these four would naturally hypothesize **K1 (stale-state substituted for current)** or **K3 (preference framing distracted the model from factual recall)** — the model consistently picks the *earlier* of two states the session reported. That was this chip's working hypothesis.

The hypothesis is wrong.

---

## Falsification: heuristic-firing audit

PR #75's heuristic (`_extract_user_context`, restored from commit `3278f31`) is re-applied to each item's `haystack_sessions`. A bullet count of 0 means the `## User context` section is **omitted** from the assembled peer card — i.e. the prompt is identical to PR #70's.

Replay confirmed:

| `question_id` | bullets PR #75 surfaced |
|---|---:|
| `830ce83f` | **0** (heuristic did not fire) |
| `9ea5eabc` | **0** (heuristic did not fire) |
| `c4ea545c` | **0** (heuristic did not fire) |
| `69fee5aa` | **0** (heuristic did not fire) |

Between PR #70's baseline commit (`64d492a`) and PR #75's baseline commit (`a49df61`), the only code touching the adapter or the dialectic prompt is `3278f31` (PR #75 itself) — the intermediate PR #72 spike (`06189df`) was reverted by `c1549e5` before the baseline. So when PR #75's heuristic returns an empty bullet list, the entire prompt — peer card, history block, dialectic instructions, system message — is byte-identical to PR #70's run.

**The four hypothesis differences are pure o4-mini stochastic re-roll on identical context.** Not a layering effect.

---

## Cross-category replication

Same audit run across all 500 items, bucketing each item by whether PR #75's heuristic fired. PR #75's actual measurable effect lives only in the fired bucket; the not-fired bucket is the stochasticity floor.

| Category | fired n | fired wins | fired losses | not-fired n | not-fired wins | not-fired losses |
|---|---:|---:|---:|---:|---:|---:|
| knowledge-update | 19 | 0 | 0 | 59 | 0 | **4** |
| multi-session | 39 | 0 | 0 | 94 | 3 | 5 |
| single-session-assistant | 6 | 0 | 0 | 50 | 0 | 0 |
| single-session-preference | 6 | 1 | 0 | 24 | 2 | 0 |
| single-session-user | 21 | 0 | 0 | 49 | 0 | 1 |
| temporal-reasoning | 35 | 2 | 1 | 98 | 2 | 3 |
| **TOTAL** | **126** | **3** | **1** (+2 net) | **374** | **7** | **13** (−6 net) |

**All 4 knowledge-update losses** (and the lone single-session-user loss, and 5 of 5 multi-session losses where the heuristic did not fire) sit in the not-fired column. They cannot be attributed to PR #75's heuristic by construction.

Decomposing PR #77's reported overall −4:

- **Heuristic effect** (items where prompt actually changed): **+2 net** (3 wins / 1 loss across 126 items; per-bucket churn 3.2%).
- **Stochastic re-roll** (items where prompt was byte-identical): **−6 net** (7 wins / 13 losses across 374 items; per-bucket churn 5.3%).
- **Sum**: −4 — matches the corpus result.

Per-bucket churn rates (3.2% fired, 5.3% not-fired) confirm the bulk of "flips" PR #77 reported are baseline o4-mini variance, not signal. The 5.3% not-fired churn happened to break −6 in this run — a directionally unlucky stochastic re-roll, not heuristic-induced regression.

---

## Disconfirmation tests

PR #68's methodology requires at least one independent disconfirmation. Three were attempted; all reinforce the same conclusion.

1. **Bullet-content audit** (per-item).
   Result: heuristic emitted zero bullets on all four items. No content from the `## User context` section could have biased model attention because no section was emitted.

2. **Cross-category baseline**.
   Result: items where the heuristic did not fire show 5.3% churn across all six categories — including categories with zero net effect (single-session-assistant 0/50, knowledge-update's 53 stable-correct + 2 stable-wrong + 4 unlucky losses). Knowledge-update's not-fired churn (4/59 = 6.8%) is within the variance band of the not-fired pool overall.

3. **Fired-vs-not-fired wins distribution**.
   Result: 2 of 3 single-session-preference "wins" PR #77 attributed to the heuristic were on items where the heuristic did not fire. The genuine heuristic-fired SPP win count is **1** (item `75f70248`), not 3. The other two SPP "wins" are stochastic re-rolls in the same not-fired pool that produced the KU losses.

---

## Structural mechanism (revised)

Knowledge-update is **not** structurally sensitive to peer-card additions. The four lost items were not affected by PR #75's heuristic at all.

The underlying mechanism is simpler and category-agnostic: **the LongMemEval corpus at n=500 with `o4-mini` as the answerer carries ~5% per-item run-to-run stochastic churn on byte-identical prompts**, which means a single full-sweep delta of ±5–10 items (±1.0–2.0pp overall) is indistinguishable from a re-roll. PR #77's strict-reading gate (overall ≥ 90.80%, no slack) correctly caught a directional regression but its **per-category attribution** of the regression to PR #75's heuristic conflated stochastic re-rolls with heuristic effect.

In the revised attribution, PR #75's actual heuristic effect on items where it fired is **+2 net** — directionally positive, but small enough relative to the not-fired stochasticity (−6) that the corpus-level overall reading flipped to −4. The PR #77 revert decision was correct on the strict promotion-gate reading, but the *cause* of the FAIL was o4-mini variance, not the heuristic.

---

## Implications for ADR 0138 forward path

PR #77's recommendation was Option C (retrieval-mechanism or ingestion-time peer-card composition), motivated by the framing "one global card serving all six task shapes has unavoidable layering cost." That framing rested on the assumption that PR #75's heuristic actively harmed knowledge-update. With that assumption falsified:

- **Option C-ii (ingestion-time category-aware composition)** is no longer load-bearing on a knowledge-update sensitivity claim. The category-conditioning argument needs a different justification — e.g. fired-bucket measurement showing differential effect across categories *where the heuristic fires* (current data: fired n is too small per category for stable estimates).
- **Option C-retrieval (Phase 4 #6.b hybrid retrieval)** still stands on its own merits (no prompt-layer engagement at all), independent of this finding.
- **Any future spike in this family** must report the fired-vs-not-fired flip table as standard methodology, not aggregate flips, to avoid re-conflating stochastic churn with heuristic effect.

ADR 0138 stays Proposed. Its falsification of Option B at the corpus layer stands — but the falsification is "the prompt-layer adapter cannot move overall accuracy enough to clear stochastic noise," not "the prompt-layer adapter actively harms non-SPP categories."

---

## Charter-discipline honest disclosure

- **n=4 is very small.** The flip-table replication across all 500 items raises this from anecdote to corpus-level signal, but the falsification is still observational, not causal proof. A second full-sweep at PR #75's commit (variance estimate) would directly measure the stochasticity floor; not in scope of this chip.
- **The 5.3% not-fired churn rate is a one-sample estimate** of o4-mini per-item stochasticity. A pre-PR #75 control sweep (same dataset, same model, same code) would be the proper baseline. The 25-min vs 54-min wall-clock difference PR #77 flagged hints that OpenRouter-side capacity may modulate stochasticity from run to run; this would need a controlled study to confirm.
- **The mechanism statement contradicts PR #77's framing.** PR #77 wrote: *"for knowledge-update items the user-context section appears to crowd out signal the model needs from the conversation history about factual updates the user reported."* This is now falsified — the user-context section was not emitted on any of the four losses. PR #77's revert verdict (strict-gate reading) remains correct; its causal attribution does not.
- **The +2 net heuristic effect is also small.** Three fired-bucket wins (1 SPP, 2 TR) against 1 fired-bucket loss (1 TR) on 126 items is well within the same stochasticity envelope. The honest reading is that PR #75's heuristic has no statistically distinguishable effect at this corpus size — neither positive nor negative — and the gate failure was driven by an unlucky re-roll on the not-fired pool.

---

## Methodology recommendation

Future LongMemEval corpus sweeps comparing adapter heuristics should report the **fired-vs-not-fired flip table** alongside the per-category delta. Without it, an adapter intervention that touches ~25% of items will have its effect estimate dominated by the stochastic re-roll noise of the untouched 75% — exactly what happened here. The fired-bucket churn rate (3.2% in this run) is the proper denominator for measuring heuristic effect; the not-fired-bucket churn rate (5.3%) is the noise floor against which any claimed effect must be discriminated.

---

## Reproduction

```bash
# Heuristic-firing audit script (one-off, written and discarded for this note)
python3 <<'EOF'
import json, re
data = json.load(open("/Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json"))
items = {d["question_id"]: d for d in data}
VERBS = re.compile(r"\bI\s+(?:prefer|like|love|hate|avoid|tried|use|own|bought)\b", re.IGNORECASE)
NEG = re.compile(r"\b(?:don'?t|won'?t|wouldn'?t|never)\s+(?:like|prefer|enjoy|want|do)\b", re.IGNORECASE)
NOT_RE = re.compile(r"\bnot\s+(?:interested in|a fan of|into)\b", re.IGNORECASE)
IDENT = re.compile(r"\b(?:I'?m|I\s+am)\s+(?:a|an)\s+\w+\b", re.IGNORECASE)
# … (see chimera/evals/longmemeval.py at commit 3278f31 for full heuristic)
EOF
```

Inputs:
- `/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl` — PR #70 graded baseline
- `/tmp/chimera-baseline-t2b-corpus/results-post-pr75.graded.jsonl` — PR #75 graded baseline
- `/Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json` — input sessions

PR #75 heuristic source: `git show 3278f31 -- chimera/evals/longmemeval.py` (now reverted on `main`).

---

## References

- [`longmemeval-baseline-post-pr75-2026-05-25.md`](./longmemeval-baseline-post-pr75-2026-05-25.md) — PR #77, the corpus FAIL baseline this note re-attributes.
- [`temporal-reasoning-regression-2026-05-25.md`](./temporal-reasoning-regression-2026-05-25.md) — PR #68, methodology template (failure taxonomy + falsification tests).
- [ADR 0138 — Implicit Preference Inference](../../docs/adr/0138-implicit-preference-inference.md) — parent ADR; stays Proposed; Option C-ii's category-sensitivity premise is weakened by this finding.
- [ADR 0139 — Heuristic-firing audit methodology](../../docs/adr/0139-knowledge-update-grounding-sensitivity.md) — captures the methodology lesson for future spikes.
