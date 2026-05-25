# ADR 0138 — Implicit Preference Inference

**Status**: Proposed (2026-05-25)

> Diagnostic-only chip. Recommends Option B (adapter grounding extension) **conditional on a single-category n=30 spike clearing two paired-item gates**; falls back to Option C (declare out-of-reach at this layer) if the spike fails. No code shipped in this ADR — the chip is the investigation that produced the recommendation.

## Context

Tier-2B from the post-T1.5 roadmap (PR #70). The post-T1.5 LongMemEval sweep shows **single-session-preference is the only category not clearing 75%** (46.67%, 14/30). Every other category clears 90%; overall is 90.80%. ADR 0137 (T1.3) addressed *explicitly stated* preferences ("when the user has stated preferences … honor them"); the remaining 16 wrong items are dominated by **implicit** preferences — context the user revealed in prior turns (a power bank, a Suica card, a lemon-poppyseed cake success) that the gold answer requires the model to transfer to a tangentially-related new question.

A "just append another prompt sentence" intervention is the obvious move and **the brief explicitly flags it as risky**. PR #68's grounding-vs-wording lesson applies: investigate before shipping a prompt change. This ADR captures that investigation.

See [`mind/research/implicit-preference-inference-2026-05-25.md`](../../mind/research/implicit-preference-inference-2026-05-25.md) for the full failure taxonomy, the disconfirmation tests, and the per-item table.

## Diagnostic outcome (from the companion research note)

Four failure classes across the 16 wrong items:

| Class | n | Notes |
|---|---:|---|
| P-HEDGE | 7 | Model returns "I don't have info on X" despite full context being in grounding |
| P-GENERIC | 6 | Generic answer; user-specific signals ignored |
| P-EMPTY | 2 | Empty hypothesis — answer-budget exhaustion, not a preference-class failure |
| P-WRONG-TOPIC | 1 | Attention/retrieval miss; orthogonal to preferences |

Three disconfirmation tests:

1. **Length comparison** — wrong items median **262 chars** vs right items median **502 chars**. Wrong items are short; consistent with hedging, not with over-answering.
2. **Right items already do implicit transfer** — the 14 right items have the same task shape (cross-topic preference transfer); the current `_DIALECTIC_PROMPT` demonstrably elicits the behavior when the model engages.
3. **Grounding-presence check** — adapter writes every user/assistant turn verbatim into the peer card. Source-data inspection confirms the relevant signal is present for **13/13** non-empty wrong items.

**Conclusion**: the residual is a **behavior-consistency cliff**, not a prompt-wording cliff or a grounding-content cliff. Both PR #66's premise (prompt-wording fix) and PR #69's premise (grounding-content fix) would target wrong layers if applied verbatim.

## Decision

**Option B — adapter grounding extension — conditional on a single-category spike.**

The chip ships as two phases:

1. **Spike (≈3 min sweep)** — implement a minimal "extract user-context turns into a `## User context` peer-card section" pass in `LongMemEvalAdapter.ingest_history`. Run `chimera evals longmemeval --subset single-session-preference` (n=30). Gate on **paired-item** criteria, not category aggregate:
   - **Gate A**: ≥2 of the 16 named wrong items (`75832dbd`, `0edc2aef`, `35a27287`, `afdc33df`, `09d032c9`, `57f827a0`, `1da05512`, `d24813b1`, `95228167`, `505af2f5`, `75f70248`, `a89d7624`, `0a34ad58`, `38146c39`, plus the 2 empties) flip to correct.
   - **Gate B**: 0 of the 14 named right items flip to wrong.
2. **Full sweep (if both gates clear)** — 500-item sweep; promotion gate is single-session-preference ≥60% **and** no other category regresses >3pp.

If Gate A or Gate B fails, the chip rolls back and the recommendation pivots to **Option C** (declare out-of-reach at the adapter+prompt layer; route to a hybrid-retrieval or ingestion-time follow-up).

## Locked-design table

| Variable | Choice |
|---|---|
| **Surface** | New private helper `_extract_user_context(item)` in `chimera/evals/longmemeval.py` returning a list of short bullet strings; inserted as `## User context` block in the synthetic self peer-card, **between** the `**Today's date:**` line and the existing `## History` header |
| **Extraction heuristic (spike)** | First user turn (topic anchor) + any user turn matching one of: `\bI\s+(have|own|like|prefer|use|bought|usually|recently|tried)\b`, `\bmy\s+\w+\b`. Cap at 6 bullets; truncate each to 200 chars |
| **Charter scope** | Chip ships **at most 5 files**: `chimera/evals/longmemeval.py` (extraction + insertion), `tests/test_longmemeval.py` (one extraction unit test + one peer-card snapshot test), `docs/adr/0138-implicit-preference-inference.md` (status flip to Accepted on gate-clear), `mind/research/implicit-preference-inference-spike-2026-05-26.md` (spike result note with paired-item table), `docs/adr/README.md` (status update) |
| **Spike gates** | Gate A (paired): ≥2/16 wrong items flip to correct. Gate B (paired): 0/14 right items flip to wrong |
| **Promotion gate (full sweep)** | single-session-preference ≥60% (≥18/30) AND no other category regresses >3pp from 90.80% baseline floor |
| **Out of scope** | Modifying `_DIALECTIC_PROMPT` (Option A explicitly ruled out by Test 2); LLM-based preference extraction (Option C-ii — separate chip); hybrid retrieval (Option C-i — deferred per PR #70); multi-session preference aggregation; changes to peer-card layout for non-LongMemEval mind dirs |

## Options considered

### Option A — Prompt extension

Append a sentence like *"When the user has not explicitly stated a preference but their prior turns reveal one, honor the inferred preference too"* to `_DIALECTIC_PROMPT`.

**Expected delta**: -2pp to +5pp on category, ±1pp overall. **Falsified by Test 2** in the companion note — right items show the current prompt already elicits this behavior 14/30 times. Adding another sentence in the face of falsifying data replays T1.2's mistake.

**Verdict**: Rejected.

### Option B — Adapter grounding extension *(chosen, conditional)*

Surface a dedicated `## User context` section in the peer card, distilled from user turns via a simple keyword heuristic. Structural analogue of PR #69's win.

**Expected delta**: +5pp to +15pp on category (assuming the spike confirms the mechanism), ±1pp overall.

**Risk**: heuristic brittleness — guarded by the spike-first protocol and paired-item gates.

**Verdict**: Recommended, conditional.

### Option C — Declare out-of-reach at this layer

Accept 46.67% as the long-term ceiling for adapter+prompt engineering on single-session-preference. Route to either:
- **C-i** — Hybrid retrieval (semantic top-k user turns surfaced as sidebar). This is the deferred Phase 4 #6.b scope per [PR #68](https://github.com/elementalcollision/chimera/pull/68#discussion).
- **C-ii** — Ingestion-time LLM-based preference extraction (`preferences.json` peer card). Separate pipeline; heavier infra.

**Expected delta**: 0pp from this chip. Defers the problem.

**Verdict**: Fallback if Option B's spike fails either gate.

## Charter-discipline notes

1. **Spike-first, paired-item reporting** — n=30 means each item is 3.33% of the category; aggregate moves of +5pp could be noise. Paired-item reporting (which specific items flipped) is the only honest disambiguation.
2. **No code in this ADR** — this is the Proposed-state ADR; the Accepted-state amendment lands in the spike PR alongside the extraction code, the spike result note, and the gate verdict.
3. **Rollback rule** — if the full sweep (post-spike) regresses any category by >3pp from 90.80% baseline, the chip rolls back regardless of the single-session-preference move. This is the standing post-T1.5 rule from PR #70.
4. **Honest disclosure** — if the spike clears Gate A by exactly 2 items (the minimum), the chip still promotes but the research note explicitly flags the result is near the noise floor.

## 2026-05-25 — Redesigned heuristic (post-PR #73 spike)

PR #72 shipped the locked-design heuristic. The ADR 0138 spike measured it
against the n=30 single-session-preference oracle:

- **Gate A: PASS** — 3 wrong→right flips (`0a34ad58`, `6b7dfb22`, `95228167`)
- **Gate B: FAIL** — 5 right→wrong flips (`1c0ddc50`, `1d4e3b97`, `32260d93`, `b6025781`, `d6233ab6`)

Per the decision tree, PR #72 was reverted (PR #74). Spike analysis
([`implicit-preference-spike-result-2026-05-25.md`](../../mind/research/implicit-preference-spike-result-2026-05-25.md))
classified the regressions: the `\bI\s+(am|'m)\b` and `\bmy\s+\w+\b` patterns
surfaced conversational filler ("I'm wondering", "my apologies") and the
heuristic missed negation/rejection ("I don't like true crime"), so stale
preferences leaked into the section. **The prominence-shape direction is
correct** — the 3 Gate A flips show that surfacing relevant user context
above `## History` does help — but the content filter was too generous.

The redesigned heuristic:

| Change | Old | New |
|---|---|---|
| Drop `\bI\s+(am|'m)\b` | matched filler | removed |
| Drop `\bmy\s+\w+\b` | matched filler | removed |
| Keep preference verbs | `I have/own/like/prefer/use/bought/usually/recently/tried/don't like/hate/love/avoid/am/'m` | narrowed to `I prefer/like/love/hate/avoid/tried/use/own/bought` |
| Add negation/rejection | (missing) | `(don't/won't/wouldn't/never) (like/prefer/enjoy/want/do)` |
| Add not-X phrases | (missing) | `not (interested in/a fan of/into)` |
| Add identity statements | (under bare `I'm`) | `(I'm/I am) (a/an) <word>` — narrower than bare `I'm` |
| Recency restriction | scanned full transcript | last 5 user turns only (drops stale-then-rejected leak) |
| Drop first-turn anchor | unconditional first user turn | removed (incidental first turns were noise) |

Cap-at-6 / 200-char truncate / dedup / empty-list-omits-section bounds preserved.

**Status stays Proposed** until the respike measures the redesigned heuristic
against the same n=30 paired-item gates. Pre-registered expectations:

- **Gate A** (≥2/16 wrong→right): expected pass — narrowing should not lose
  most of the prominence-shape signal.
- **Gate B** (0/14 right→wrong): the load-bearing gate — must be met.
- **Supplementary regression check**: the 3 items that flipped wrong→right in
  PR #73's spike (`0a34ad58`, `6b7dfb22`, `95228167`) should still flip in
  this respike; if any go right→wrong, the redesign is over-narrow.

If Gate A passes and Gate B fails again, the prominence-shape direction is
right but no current heuristic is sharp enough — fall back to Option C
(hybrid retrieval or ingestion-time preference extraction). If Gate A fails,
the prominence-shape direction is wrong — also Option C.

The respike is operator-fired post-merge of this chip's PR; no code in this
chip runs the spike.

## References

- [`mind/research/implicit-preference-inference-2026-05-25.md`](../../mind/research/implicit-preference-inference-2026-05-25.md) — the diagnostic this ADR rests on.
- [`mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md`](../../mind/research/longmemeval-baseline-post-t1.5-2026-05-25.md) — post-T1.5 baseline.
- [`mind/research/temporal-reasoning-regression-2026-05-25.md`](../../mind/research/temporal-reasoning-regression-2026-05-25.md) — PR #68 methodology template.
- [ADR 0135 — LongMemEval adapter](./0135-longmemeval-integration.md).
- [ADR 0136 — Temporal-Aware Dialectic](./0136-temporal-aware-dialectic.md).
- [ADR 0137 — Preference-Aware Dialectic](./0137-preference-aware-dialectic.md) — sibling for *explicit* preferences.
- [PR #68](https://github.com/elementalcollision/chimera/pull/68) — investigation-only template.
- [PR #69](https://github.com/elementalcollision/chimera/pull/69) — T1.5 grounding-extension shipping template (Option B's analogue).
- [PR #70](https://github.com/elementalcollision/chimera/pull/70) — post-T1.5 baseline.
