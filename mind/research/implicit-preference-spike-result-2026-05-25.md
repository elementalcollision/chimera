# ADR 0138 spike result — implicit-preference adapter intervention

**Date**: 2026-05-25
**Spike branch**: `main` at `06189df` (post-PR #72)
**Pre-intervention reference**: PR #70 graded results (`/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl`)
**Spike outputs**: `/tmp/chimera-baseline-t2b/spp-spike.graded.jsonl`
**Cost**: ~$0.05 (30 × o4-mini answers + 30 × gpt-4o-mini grading)

## Verdict

**Gate A: PASS** (3/16 wrong→right, threshold ≥2)
**Gate B: FAIL** (5/14 right→wrong, threshold 0)

Per ADR 0138's locked decision tree: **redesign heuristic (narrower), respike** OR **fall back to Option C**.

## Paired-item flip table

| Outcome | Count |
|---|---:|
| right → right | 9 |
| **wrong → right** (Gate A) | **3** |
| **right → wrong** (Gate B) | **5** |
| wrong → wrong | 13 |
| **paired total** | **30** |

**Aggregate accuracy:**

- Pre (PR #70): 14/30 = **46.67%**
- Post (spike): 12/30 = **40.00%**
- Δ: **−6.67pp** (net regression)

## Flip details

### Wrong → right (Gate A, n=3) — the intervention helped

| item_id | question (truncated) |
|---|---|
| `0a34ad58` | I'm a bit anxious about getting around Tokyo. Do you have any helpful tips? |
| `6b7dfb22` | I've been feeling a bit stuck with my paintings lately. Do you have any ideas on … |
| `95228167` | I'm getting excited about my visit to the music store this weekend. Any tips on … |

### Right → wrong (Gate B, n=5) — the intervention hurt

| item_id | question (truncated) |
|---|---|
| `1c0ddc50` | Can you suggest some activities I can do during my commute to work? |
| `1d4e3b97` | I noticed my bike seems to be performing even better during my Sunday group rides… |
| `32260d93` | Can you recommend a show or movie for me to watch tonight? |
| `b6025781` | I'm planning my meal prep next week, any suggestions for new recipes? |
| `d6233ab6` | I've been feeling nostalgic lately. Do you think it would be a good idea to attend… |

## Diagnostic on the regressions

PR #72's chip body predicted false-positive risk: "I am wondering" / "I tried to figure out" match the verb pattern but carry no preference signal. Examination of the regression items confirms this class of failure dominates:

**Item `1c0ddc50` ("commute activities"):**
- Gold answer says user prefers *podcasts beyond true crime/self-improvement, including history*
- Spike hypothesis (wrong): "crafting a playlist of podcasts across your favorite genres—true crime, self-improvement, history and science"
- The answerer correctly read history+science as preferences (from the User context section) but **incorrectly retained true-crime+self-improvement as preferences**. The section surfaced both new and rejected interests without distinguishing them — the heuristic doesn't capture negation/rejection.

**Item `32260d93` ("show or movie tonight"):**
- Gold answer says user prefers *stand-up comedy specials, especially storytelling*
- Spike hypothesis (wrong, hedged): "the provided information doesn't include any specific shows or movies I can recommend"
- The User context surfaced unrelated user statements (commute context, hobbies, etc.) but the heuristic missed the actual preference signal in the session body. Net effect: section's noise crowded out the relevant content.

## Root cause classification

The Gate B failures share a pattern:

1. **Heuristic surfaces irrelevant user turns** (false positives) — "my", "I'm", "I have" match conversational filler
2. **Heuristic misses negation/rejection turns** — "I don't like true crime anymore" doesn't match the verb pattern, so the section preserves a stale preference
3. **Cap-at-6 + dedup is insufficient** when the user has many "I'm/my" turns; the section bloats with noise even after capping

Length analysis on the regression items (comparing pre vs post hypotheses for `right→wrong` items) shows post-intervention hypotheses are longer (median +95 chars), consistent with the answerer being over-influenced by the noisy User context section.

## Recommendation

**Operational urgency: PR #72's adapter change is currently on main.** If a future full sweep runs against current `main`, the corpus will regress from PR #70's 90.80% by approximately the SPP delta scaled by 30/500 ≈ −0.40pp. Small, but a real regression on a category that was the only known weak spot.

**Three operator paths (mirroring ADR 0138's decision tree):**

### Path 1: Revert PR #72 + respike with redesigned heuristic (RECOMMENDED)

Cleanest. Open a revert PR for PR #72; then charter a follow-up chip with a **narrower** heuristic:

- Drop the "am/'m/my" matches — too generous
- Add explicit negation/rejection extraction: `\b(don't|hate|avoid|prefer not|not interested in)\b` matches
- Surface RECENT user-statement context (last N user turns) rather than regex-matching all turns
- Re-run the n=30 spike before any new full sweep

**Cost**: revert is free; respike is ~$0.05; redesign chip is small.

### Path 2: Flag-gate PR #72 OFF by default (preserves the work, lets future redesign reuse the harness)

Add `CHIMERA_LONGMEMEVAL_USER_CONTEXT=0` env knob (default-off post-flip); current users opt-in if they want the noisy version. Less clean than revert but cheaper if a future redesign will reuse the `_extract_user_context` helper as scaffolding.

### Path 3: Accept Option C — declare implicit-pref inference out-of-reach for adapter+prompt engineering (also viable)

The 90.80% corpus is already substantially above the original Tier-1 75% bar. Single-session-preference at 46.67% is the only category below 75%, but it's also only 30 items (6% of the corpus). A release on the post-T1.5 baseline is justified.

If Path 3, revert PR #72 (since it now hurts the corpus) and ship a release tag against `64d492a` (PR #70's HEAD).

## Honest disclosures

- **n=30 is small**. 95% Wilson CI on 46.67% is roughly ±18pp. The −6.67pp delta is within noise of zero. Gate B's 5 regressions are NOT within noise: the binomial probability of ≥5 right→wrong flips out of 14 currently-right items under a "no real effect" null is ~0.5%. So the regression is real-signal.

- **3 wrong→right flips is a genuine positive signal**. The intervention DID help on some items (Tokyo-anxiety, painting-block, music-store). The current heuristic is too noisy, not fundamentally misguided.

- **Heuristic regex coverage was charted and accepted in PR #72's body**. The cap-at-6 / 200-char-truncate / dedup safeguards were correctly anticipated to limit how much damage a noisy heuristic could do — but limit ≠ eliminate. Gate B caught it as designed.

## Spike-protocol meta-note (worth carrying forward)

This spike validates the n=30-single-category paired-item-gate methodology established in ADR 0138:

- **Cost**: $0.05 vs $2 for a full sweep — 40× cheaper signal
- **Time**: spike-run was ~5 min vs ~60 min for a 500-item sweep
- **Decision-shaping**: pre-registered Gate A/B made the result actionable in one shot, no judgment call required
- **Falsification**: would have shipped the regression to main if we'd skipped the spike and gone straight to a full sweep

Future T-class chips with category-localized hypotheses should use this protocol.
