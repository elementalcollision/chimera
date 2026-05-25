# Temporal-reasoning regression — investigation (2026-05-25)

**Trigger**: [`longmemeval-baseline-2026-05-25.md`](./longmemeval-baseline-2026-05-25.md) flagged temporal-reasoning at 53.38% (71/133) as a −46.62pp regression from the 5-item smoke headline. The note hypothesised that T1.2's added cross-session sentences in `_DIALECTIC_PROMPT` (PR #64, ADR 0136) may have biased the answerer toward narrative integration on items whose gold answer is a single value.

**This chip's job** is to test that hypothesis against the actual graded sweep, then either (a) ship a tightened prompt or (b) recommend the correct downstream chip and stop.

**Verdict**: hypothesis (a) — prompt wording over-applies — is **NOT supported** by the data. The failure mode is hypothesis (b) — **grounding missing session timestamps**. The recommended next chip is a temporal-grounding follow-up (or rolled into T2.1 hybrid retrieval), NOT a prompt rephrase. No code change ships from this chip.

---

## Method

Pulled all 133 temporal-reasoning rows from `/tmp/chimera-baseline/results-post-tier1-graded.jsonl` (the full-sweep graded output that produced the headline 53.38%). Split into 71 correct / 62 wrong. Read the first 15 wrong rows in full (question + gold + hypothesis) by hand, then ran a lexical classifier over all 62 wrong hypotheses to build the failure taxonomy.

## Failure taxonomy (n = 62 wrong)

| Class | Count | % of wrong | What the hypothesis looks like |
|---|---:|---:|---|
| **B1 — hedged ignorance** | 28 | 45.2% | *"I'm sorry, but the provided details don't include the specific dates… so I can't determine how many days passed."* |
| **B2 — "today/yesterday/zero"** | 20 | 32.3% | *"You attended the Maundy Thursday service today, so it was zero days ago."* (gold: 4 days ago) |
| **C — wrong value or wrong topic** | 14 | 22.6% | Wrong numeric answer, or — in one case — answered an unrelated question (shoe cleaning method instead of which pair). |

**Classes B1 + B2 are the same root cause: the model has no anchor date**. The session text contains relative phrases ("today", "just downloaded", "yesterday") and no absolute date; the assembled dialectic prompt does not expose the session's send-timestamp. The model either honestly hedges (B1) or naively maps "today" to "0 days ago" (B2). Together these are **48/62 = 77.4%** of all temporal misses.

Class C (14/62 = 22.6%) is a grab-bag — some are arithmetic errors on items where dates *were* present, some are retrieval failures (wrong session selected). These are not attributable to prompt wording either.

### Cross-check: what the correct items look like

The 71 correct hypotheses cite absolute dates that appear in the source text — *"You attended the workshop on January 10th, and since your team meeting was on January 17th…"*, *"You received your Samsung Galaxy S22 on February 20th…"*. The model handles temporal arithmetic correctly **when the absolute dates are in the grounding**. The failures cluster exactly on items where the user wrote *"today"* and the model has nothing to anchor against.

### Length check (sanity test for the "narrative-drift" hypothesis)

If T1.2's wording were producing narrative drift away from a single value, wrong hypotheses should be **longer** than correct ones (more rambling integration). Observed:

- Wrong hypothesis median length: **131 chars**
- Correct hypothesis median length: **159 chars**

Wrong hypotheses are *shorter* than correct ones, the opposite of what the narrative-drift hypothesis predicts. The hedged-ignorance class drives this — *"I'm sorry, no dates"* is short. This is independent confirmation that the failure mode is not the prompt's narrative bias.

## Which of the chip's hypotheses fits?

| Hypothesis | Evidence | Fit |
|---|---|---|
| **(a) T1.2 wording over-broad — biases toward narrative integration** | Wrong hypotheses are *shorter*, not longer. Failures cluster on items with no absolute dates, not on cross-session-vs-single-session split. | ❌ Rejected |
| **(b) Latent retrieval / grounding bias — model didn't find the right session or the right anchor** | 77.4% of misses are "no date anchor available". The grounding sources (peer card / decisions / beliefs) carry no per-session timestamps. | ✅ Confirmed |
| **(c) Gold-answer-format mismatch** | Spot-checked B1/B2 hypotheses against gold — these are substantive mismatches ("0 days ago" ≠ "4 days ago"), not formatting. | ❌ Rejected |

## Why a prompt tweak would not help

The chip charter's proposed rephrasing —

> *"When the question explicitly requires information that spans multiple sessions, integrate facts across the entire history; otherwise answer from the most directly relevant session."*

— is a sensible refinement in isolation, but it changes *how* the model integrates available facts. The 77% root cause is that **the facts the model needs (session send-dates) are not in the prompt at all**. No reshuffling of the integration directive recovers a date that was never grounded. Shipping the rephrase would produce a null-to-marginal result at best, and would burn the operator's ~$2 sweep budget on a null finding.

## Recommended next chip

Two options, in priority order:

1. **Roll the fix into T2.1 (Phase 4 #6.b hybrid retrieval)** — the retrieval surface is the natural place to attach session timestamps to surfaced turns. The merge gate already includes "must not regress temporal-reasoning". Make the gate stronger: **must not regress temporal-reasoning AND must move it by ≥15pp**. Drop the prompt-only chip.
2. **If T2.1 slips**, ship a small standalone chip: extend `gather_dialectic_context` (or the LongMemEval adapter's call into it) to surface each session's timestamp in the assembled prompt — e.g. a "── Session timeline ──" block listing `(session_id, sent_at)`. This is a context-shape change, not a prompt-wording change; ADR-worthy as a small follow-up to ADR 0135 or as an amendment to ADR 0136.

Either path is the operator's call. This chip recommends path 1 — the failure mode and the planned next chip line up too neatly to justify a separate prompt-only chip in between.

## No prompt edit, no ADR amendment

Per the chip charter, the "ship" phase is gated on failure mode (a) being dominant. (a) is not supported. The chip stops here. ADR 0136 stays as written. `_DIALECTIC_PROMPT` is untouched. `tests/test_dialectic.py` is untouched.

## Hypothesis-test plan if a prompt rephrase is shipped later anyway

Recorded for completeness — not requested by this chip.

1. Smoke (`--n-per-category 5`) on the temporal category alone; expect ≤±20pp swing as noise. A move <15pp in either direction is consistent with null.
2. Full sweep (500 items) for the load-bearing number. Promotion gate: temporal-reasoning ≥75% AND overall ≥80%.
3. If smoke is null or negative, do not run the full sweep — saves the ~$2.

## References

- [longmemeval-baseline-2026-05-25.md](./longmemeval-baseline-2026-05-25.md) — the regression flag and the hypothesis space.
- [ADR 0136 — Temporal-Aware Dialectic](../../docs/adr/0136-temporal-aware-dialectic.md) — the prompt change under examination (not modified by this chip).
- [`chimera/a2a/dialectic.py`](../../chimera/a2a/dialectic.py) — `_DIALECTIC_PROMPT` at line 156 (the grounding-shape question lives upstream of this prompt, in `gather_dialectic_context`).
- Graded sweep data: `/tmp/chimera-baseline/results-post-tier1-graded.jsonl` (500 rows, oracle distribution, post-Tier-1 main at `7e379ae`).

## READY-FOR-REMEDIATION

No remediation in this chip. Recommended remediation owner: **T2.1 (Phase 4 #6.b hybrid retrieval)** — extend that chip's scope to include surfacing per-session timestamps in the assembled grounding, and tighten its merge gate to require **temporal-reasoning ≥68% (≥+15pp from 53.38%) AND overall ≥80%**.
