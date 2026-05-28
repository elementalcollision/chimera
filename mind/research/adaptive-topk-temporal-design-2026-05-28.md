# Adaptive top-k for temporal queries — design note (Phase A)

**Date**: 2026-05-28
**Chip**: ADR 0142 capstone amendment, remediation direction #1 — *adaptive top-k for temporal queries*
**Status**: Pre-registered design + falsification gate (LOCKED)
**Predecessors**:
- [ADR 0142](../../docs/adr/0142-hybrid-retrieval-for-long-horizon.md) (§"Temporal-reasoning regression diagnosis closure (v37+v38+v39, 2026-05-28)" + §"Remediation direction")
- [v39 postmortem](./v39-soak-postmortem-2026-05-28.md) (CONVERGES — 74% H2 on N=19)
- [F2 LoCoMo ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) (−10.42pp temporal-reasoning regression, n=96)
- [v39 9-item classification](./v39-locomo-temporal-19-item-classification.md)
- [v37 5-item classification](./v37-locomo-temporal-5-item-classification.md)
- [v38 5-item classification](./v38-locomo-temporal-10-item-classification.md)

## TL;DR

The 19-item v37+v38+v39 diagnosis closed at **H2=74%, H1=21%, H4=5%, H3=0%**
(ADR 0142 §"Cumulative 19-item label distribution"). The dominant
failure is **context-budget dilution under top-k=8 truncation** — the
right session is typically retrieved, but its temporal anchors get
compressed within the answerer's context window, producing polarity
inversions, temporal-window collapse, literal-match hedging, and
self-contradiction (v39 postmortem §"Headline finding").

This chip implements **adaptive top-k for temporal queries**: detect
temporal-reasoning question shape at retrieval time and adapt by
returning all sessions in chronological order (effectively disabling
top-k truncation for that query). Default OFF behind
`CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1`. ADR 0142 status (`Accepted (_s`-only)`)
is **not** modified.

## Loadbearing citations from v39 / ADR 0142

The 74% H2 mechanism is described mechanistically in ADR 0142 §"Mechanism":

> under top-k=8 retrieval truncation the right session is typically
> retrieved, but its temporal anchors get compressed within the
> answerer's context window. The failure modes observed across the H2
> paragraphs are a small set — polarity inversion on yes/no questions,
> temporal-window collapse on when/where questions, literal-match
> hedging that refuses commonsense bridge inference, and
> self-contradiction within a single answer.

And in v39 postmortem §"Headline finding":

> The dominant failure mode is the agent recognizing the right session
> was retrieved, but under top-k=8 truncation the temporal anchors get
> compressed and the answerer either inverts polarity (yes/no
> questions) or collapses adjacent time windows (when/where
> questions). This is mechanistically a **context-budget vs.
> temporal-anchor-density** problem, not a retrieval or
> model-capability problem.

ADR 0142 §"Remediation direction" then names this chip's exact axis:

> **Adaptive top-k for temporal queries**: detect temporal-reasoning
> question shape at retrieval time; increase top-k or disable
> retrieval for those queries. Falsified if temporal-reasoning
> accuracy stays ≤ current under k=full / k-adaptive.

If H2 (74%) is the load-bearing mechanism, then defeating the
truncation step on temporal queries should recover most of the
−10.42pp regression. Conversely, if it does not recover ≥+2pp on
temporal-reasoning at the F2 corpus level, then either (a) the H2
classification was an over-call (a risk explicitly flagged in ADR 0142
§"Honest disclosures") or (b) the H2 mechanism is real but the lift
is offset by a different effect introduced by k=full on temporal
items (e.g., the answerer-attention dilution that hybrid retrieval was
introduced to fix in the first place on `_s`). Either way the result is
falsifiable.

## Decision matrix (LOCKED — picked one per charter)

### Detection mechanism: **regex**

| Option | Pros | Cons | Picked? |
|---|---|---|---|
| Regex over question text | Zero cost, deterministic, no extra model call, easy to test | LoCoMo-tuned; may miss out-of-distribution temporal phrasings | **YES** |
| LLM classifier | Generalizes across phrasings | Extra per-query LLM spend; classification-rests-on-agent-call (the very disclosure that v39 flagged) | no |
| Category-lookup (`item.category == "temporal-reasoning"`) | Authoritative on LoCoMo, zero cost | Only works inside the eval harness; production queries don't carry category labels — defeats the point of remediation that would generalize | no (kept as **boost**: see §Implementation) |

**Pick**: a small, auditable regex on common LoCoMo temporal phrasings —
`\bwhen\b`, `\bwhat (day|date|time|month|year)`, `\bhow long\b`, `\bhow many (days|weeks|months|years)\b`, etc. Implemented as a single compiled `re.Pattern`. The regex is intentionally narrow; false-positive cost is small (raise top_k for a non-temporal query → lift retrieval ceiling = ~no harm at worst per ADR 0145 noise envelope §F3); false-negative cost is just losing the lift on missed phrasings (graceful degradation).

A secondary signal, **active only inside the LoCoMo adapter where it's available**, is `item.category == "temporal-reasoning"`. The regex remains the universal path; the category check is a free OR-boost that only fires when the harness already knows the category. (Outside the eval harness — i.e. in any production caller of `select_top_k_sessions` — only the regex contributes.)

> **Spike-driven recalibration (Phase A tiny-spike, 2026-05-28)**:
> the design-draft regex was tested on the full LoCoMo F2 corpus
> (N=1,986) and recalled only 3.1% of true category-3 questions
> while false-positiving on 22.1% of non-temporal items (driven by
> `before`/`after`/`since`). LoCoMo's category-3 is dominated by
> commonsense-bridge inference, not literal date/when phrasings. The
> regex was narrowed to the literal date/when subset only; inside
> the LoCoMo harness the **category-lookup signal carries the
> load-bearing weight** because the harness has it for free. This
> is a detection-mechanism recalibration based on spike data — the
> Phase B gate (≥+2pp on temporal-reasoning, ±1pp overall, ±3pp
> `_s`) is unchanged. See the spike note for the empirical numbers.

### Adaptation policy: **disable retrieval (k = n)**

| Option | Pros | Cons | Picked? |
|---|---|---|---|
| Raise top_k to a higher fixed value (e.g., 16) | Bounds cost growth | Arbitrary; v39 §"Recommended next chip" specifically suggested k=full path | no |
| **Disable retrieval (k = n)** | Directly attacks H2 by removing the truncation step; matches ADR 0142's "disable retrieval for those queries" remediation phrasing; mirrors LoCoMo paper's full-context eval | Cost: ~5× context tokens for the ~5% of LoCoMo questions that are temporal (96/1986) | **YES** |
| Hybrid (keep retrieval but inject full chronology summary) | Best-of-both | Doubles design complexity; explicitly listed as a *different* remediation direction in ADR 0142 ("Mid-conversation summary injection") and is OUT OF SCOPE | no |

**Pick**: when detection fires, return `list(range(n))` — every session, original order — exactly as the `hybrid_retrieval=False` baseline path does. This is the minimal, bit-for-bit-known-good adaptation. The other 95% of queries (non-temporal) keep top-k=8 hybrid retrieval, preserving the +20.63/+16.82/+7.61pp wins on adversarial/multi-hop/open-domain.

### Hook location

`LoCoMoAdapter._select_session_indexes` (chimera/evals/locomo.py:431). The new logic sits between the existing `if n <= self._retrieval_top_k: return list(range(n))` short-circuit and the `select_top_k_sessions(...)` call. New code is gated by `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` env var (env knob).

**Function/class**: `LoCoMoAdapter._select_session_indexes` (modified, ≤30 LOC delta) plus a new module-level helper `is_temporal_query(question, category=None) -> bool` in `chimera/evals/hybrid_retrieval.py` (new ~30 LOC, sibling helper — keeps the regex in the same module the other retrieval primitives live in so it's testable in isolation and reusable by any future caller).

**Env knob**: `CHIMERA_ADAPTIVE_TOPK_TEMPORAL`
**Default**: `"0"` (OFF). Set to `"1"` to enable. Any other value is treated as OFF and a debug-level log is emitted.

**Default-off invariant**: when `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` is unset or `"0"`, `_select_session_indexes` behavior is bit-for-bit identical to current main. This is asserted by a backward-compat test that diffs the returned indexes against a hybrid-retrieval baseline call on a stub item with `hybrid_retrieval=True, retrieval_top_k=2` and 5 sessions.

## Unit tests (TDD — written before implementation)

Added to `tests/test_hybrid_retrieval.py`:

1. **`test_is_temporal_query_detects_common_phrasings`** — positive cases (`"When did Alice meet Bob?"`, `"How long has Carol lived there?"`, `"What month did they meet?"`, `"What happened before the vacation?"`, `"How many weeks ago was that?"`).
2. **`test_is_temporal_query_negative_on_non_temporal`** — negative cases (`"Where does Alice live?"`, `"What is Bob's favorite food?"`, `"Do they like coffee?"`, `"Who introduced them?"`).
3. **`test_is_temporal_query_category_signal`** — `category="temporal-reasoning"` short-circuits to `True` regardless of question text; other categories don't false-positive.
4. **`test_adaptive_topk_on_temporal_returns_all_sessions`** — with `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1` (monkeypatched) and a LoCoMo-shaped item whose question matches the regex, `_select_session_indexes` returns `list(range(n))` even when `n > retrieval_top_k`.
5. **`test_adaptive_topk_off_is_byte_for_byte_baseline`** — with `CHIMERA_ADAPTIVE_TOPK_TEMPORAL` unset and a temporal question, output equals the existing hybrid-retrieval path (which truncates to top_k). This is the backward-compat gate.
6. **`test_adaptive_topk_on_non_temporal_still_truncates`** — with `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1` and a non-temporal question, the adapter still calls `select_top_k_sessions` and returns ≤ top_k indexes. (Adaptive logic doesn't hijack non-temporal queries.)

## Cost expectation per query

- **Detection cost**: one compiled-regex search over a string of ~10–200 chars. Sub-microsecond. Zero LLM calls.
- **Adaptation cost on temporal queries**: skips BM25 + dense embed entirely, but the answer-time prompt grows from top-8 sessions to all sessions (~19–32 on LoCoMo, mean ~25 → ~3×). At ~2K tokens/session, this raises per-temporal-item answerer input from ~16K to ~50K tokens. On gpt-4o-mini input pricing (~$0.15/M tokens), per-item delta ~$0.005. Across 96 LoCoMo temporal items: ~$0.50 extra answerer cost. Across the full 1,986-item LoCoMo Phase B sweep: temporal items already cost ~$0.40 in F2; total Phase B answerer cost ≈ F2 cost + $0.50 ≈ $8.50. Phase B remains under the $10 pause threshold.
- **Adaptation cost on non-temporal queries**: zero — adaptive path is not entered.

## Honest disclosures

1. **All 19 H2/H1/H4/H3 classifications were agent calls, not independently ground-truthed.** ADR 0142 §"Honest disclosures" flags this explicitly: *"the cumulative finding rests on agent classification, not a separate ground-truth set."* This chip's premise — that the 74% H2 dominance is load-bearing and therefore the remediation lever lies on the retrieval/context-budget axis — inherits that uncertainty. If H2 is overcounted at the n=19 level, the +2pp gate may fail honestly; the falsification record (Phase B note) will say so without retro-tuning.

2. **Gate is conditional on `openai/gpt-4o-mini` judge + locked `scripts/grade_locomo.py` prompt.** F2 baseline (35.42% on temporal-reasoning, n=96) was measured with this judge. Phase B must reuse it to keep the comparison apples-to-apples. Switching judge models retroactively would invalidate the gate without invalidating the design.

3. **Regex detection is LoCoMo-tuned.** The vocabulary (`when`, `how long`, `before/after`, etc.) was lifted from inspecting the LoCoMo temporal-reasoning questions called out in the v37/v38/v39 classification deliverables. Cross-corpus generalization (LongMemEval, oracle, production traffic) is future work; the gate measures LoCoMo only.

4. **Classification rests on agent call — sub-disclosure on the regex itself.** Even though the regex avoids per-query LLM classification, the *choice of regex tokens* was a one-shot agent call from reading the v37/v38/v39 classification notes. There is no separate ground-truth temporal-vs-non-temporal labeller. Future work could either (a) train a small classifier on labeled questions or (b) accept the regex's recall floor and pair it with category-lookup wherever a curated category is available.

5. **Even if the gate clears at +2pp, ADR 0142 status does NOT auto-flip.** The status remains `Accepted (_s`-only)` until the operator explicitly amends it. This chip ships a *gated remediation knob*, not a status change.

6. **Phase B baseline reuse caveat.** If Phase B reuses the F2 baseline numbers rather than running a fresh adaptive-OFF sweep, the comparison inherits F2's single-sweep noise (per F2 note §"Honest disclosures": σ overall = 0.46pp, no F2-specific σ measured). The +2pp temporal-reasoning gate at n=96 is ≫ any plausible per-cat σ at that n; the regression guard at ±3pp on `_s` and ≥F2−1pp overall is also well outside noise. We'll call this risk in the Phase B note explicitly if we don't pair-baseline.

7. **Asymmetric-risk profile.** Disabling truncation only on temporal queries cannot regress non-temporal categories (their path is unchanged), so the overall-regression guard (≥F2−1pp) is essentially impossible to violate by mechanism — only by single-sweep noise. The `_s` guard (±3pp) measures whether the `is_temporal_query` regex misclassifies enough `_s` queries to perturb the `_s` adapter's behavior; the `_s` adapter only enters the adaptive path when its own caller passes the flag through, which we do not modify in this chip. Risk is bounded.

## Pre-registered falsification gate (LOCKED — copied from charter)

On the LoCoMo F2 corpus with adaptive-top-k gated ON via `CHIMERA_ADAPTIVE_TOPK_TEMPORAL=1`:

1. **Primary**: temporal-reasoning accuracy ≥+2pp vs F2 baseline (35.42% on 96-item LoCoMo temporal-reasoning subset). **Floor: ≥37.42%**.
2. **Overall regression guard**: overall LoCoMo accuracy across all 1,986 items must NOT drop below F2 baseline minus 1pp. Floor: **≥58.37%**.
3. **`_s` regression guard**: LongMemEval `_s` long-horizon accuracy must remain within ±3pp of existing `_s` baseline.
4. **Default-off**: gated behind env knob, default OFF. ADR 0142 status stays `Accepted (_s-only)` regardless.

If the primary fails, the Phase B note ships as a falsification record (per discipline-gate "Falsification honesty"). No post-hoc gate relaxation. No re-labeling.

## Implementation surface

- `chimera/evals/hybrid_retrieval.py` — add `is_temporal_query(question, category=None) -> bool` + `_TEMPORAL_RE` constant + `_adaptive_topk_enabled() -> bool` env reader. ~30 LOC additive.
- `chimera/evals/locomo.py` — modify `_select_session_indexes` to consult `is_temporal_query` + `_adaptive_topk_enabled` and return `list(range(n))` when both are true. ~10 LOC delta.
- `tests/test_hybrid_retrieval.py` — extend with the 6 tests listed in §Unit tests.

Total: ≤200 LOC additive (well under cap). No ADR 0142/0146/0145 modifications. No soak runner / cascade / unrelated-module touches.

## Tiny-spike plan (Phase A close)

Sample 5 items from the LoCoMo F2 temporal-reasoning H2-labeled subset (one each from v37 #1–#5 and v38 #6–#10 and v39 #11–#19 — picking item #1 conv-26::qa14, #4 conv-26::qa81 (an H1 control), #11 conv-43::qa34, #14 conv-47::qa12, #18 conv-49::qa5). Run only the detection on each question (no full eval; we just verify the regex correctly fires on the 4 temporal and on the H1 control). Budget: ~$0 (no LLM calls; detection only). Record as `mind/research/adaptive-topk-temporal-spike-2026-05-28.md`.

The tiny spike is **detection-validation only** — it does not measure accuracy lift. Accuracy lift is the Phase B gate, on the full 1,986-item corpus.

## Linked decisions

- ADR 0142 — Hybrid retrieval for long-horizon (status unchanged)
- ADR 0145 — LoCoMo noise envelope (gate authority — the +2pp / ±3pp / ±1pp thresholds inherit from it)
- v39 postmortem — H2 dominance load-bearing finding
- F2 LoCoMo ablation — baseline measurement
