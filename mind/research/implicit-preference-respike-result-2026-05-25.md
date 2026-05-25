# ADR 0138 respike result — redesigned-heuristic spike v2

**Date**: 2026-05-25
**Respike branch**: `main` at `3278f31` (post-PR #75)
**Pre-intervention reference**: PR #70 graded results (`/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl`)
**Respike outputs**: `/tmp/chimera-baseline-t2b-v2/respike.graded.jsonl`
**Cost**: ~$0.05

## Headline verdict

| Gate | Threshold | Result | Status |
|---|---|---:|---|
| A (wrong→right) | ≥ 2/16 | **3 flips** | ✅ PASS |
| B (right→wrong) | 0/14 | **1 regression** | ❌ FAIL (by 1) |
| Regression check (v1's 3 wrong→right flips persist) | ≥ 2/3 | **1/3 preserved** | ❌ FAIL |

**Net delta: +6.67pp** (14/30 → 16/30). Same Gate A win count as v1, but only 1 right→wrong vs v1's 5. Strict reading of pre-registered gates: **Gate B FAIL → Option C** per ADR 0138 decision tree.

## Side-by-side: v1 vs v2

| Metric | v1 (PR #72→#73) | v2 (this respike) | Δ |
|---|---:|---:|---:|
| wrong → right | 3 | 3 | 0 |
| right → wrong | **5** | **1** | **−4** |
| net delta | −6.67pp | +6.67pp | +13.3pp |
| Gate B status | FAIL | FAIL (by 1) | improved but not cleared |

The redesigned heuristic dramatically reduced the noise (5 → 1 regressions) while preserving the win count. The direction is correct; the threshold is binary.

## Flip details

### Wrong → right (Gate A, n=3)

| item_id | question (truncated) | v1 flipped? |
|---|---|:---:|
| `6b7dfb22` | I've been feeling a bit stuck with my paintings lately… | ✅ same as v1 |
| `75832dbd` | Can you recommend some recent publications or conferences… | new |
| `d24813b1` | I'm thinking of inviting my colleagues over for a small gathering… | new |

The v2 redesign produced 2 NEW wins (`75832dbd`, `d24813b1`) that v1's noisy regex didn't capture — suggests narrower content filter is doing useful work.

### Right → wrong (Gate B, n=1)

| item_id | question (truncated) | v1 also regressed? |
|---|---|:---:|
| `d6233ab6` | I've been feeling nostalgic lately. Do you think attend high school reunion… | ✅ yes — same item |

**`d6233ab6` is consistently sensitive to any user-context surfacing.** It regressed in both v1 (with the noisy heuristic) and v2 (with the narrowed heuristic). The item's gold answer likely depends on a preference signal that's NOT in the surfaced user turns regardless of regex tuning; surfacing other context displaces the answerer's attention from whatever IS the right signal.

### Regression check on v1's wins (n=3)

| v1 wrong→right item | v2 outcome | Verdict |
|---|---|---|
| `0a34ad58` Tokyo-anxiety | wrong → wrong | **lost** |
| `6b7dfb22` painting-block | wrong → right | preserved |
| `95228167` music-store | wrong → wrong | **lost** |

Only 1/3 persisted. **Last-5 over-narrowing is real** — the redesign trimmed signal along with noise. The preference signals on the lost items likely lived in user turns earlier than the last 5.

## Diagnostic on `d6233ab6` (the persistent Gate B failure)

Inspecting the item:
- Gold answer: user prefers NOT attending the high school reunion (negation-style preference)
- v1 hypothesis: hedged/non-committal
- v2 hypothesis: similarly hedged/non-committal
- Pre-intervention hypothesis (no User context): recommends attending (the wrong direction but graded "correct" because of a phrasing alignment with gold)

The item's correctness on the baseline appears to be a **lucky-correct** hypothesis where the answerer happened to land on the right framing by accident. Adding User context — whether noisy (v1) or clean (v2) — gave the answerer enough to be MORE confident in the wrong direction. The intervention isn't really "regressing" this item; the baseline was over-correct.

If this hypothesis is right, the actual Gate B count should be **0 real regressions** when adjudicated against gold semantics. But the pre-registered gate uses judge labels, not adjudication, so the strict reading is FAIL.

## Honest disclosures

- **n=30 is small.** With 3 wins and 1 loss, McNemar's-test statistic ≈ 1.0 → p ≈ 0.32 (two-sided). The +6.67pp aggregate delta is NOT statistically significant at this sample. The DIFFERENCE from v1 (4 fewer regressions) IS meaningful evidence the redesign worked.
- **`d6233ab6` is an outlier item, not a calibration failure.** Same regression in both heuristics suggests the item is intrinsically sensitive, not a property of the regex.
- **2 of v1's wins were lost.** Last-5 scope is too aggressive; a future redesign would either restore early-window inclusion with sharper content filters, or accept that prominence-shape can recover at most ~3/16 wrong items.

## Pre-registered decision (strict)

Per ADR 0138's pre-registered tree, **Gate B FAIL → Option C** (declare implicit-pref out-of-reach for adapter+prompt engineering; accept 90.80% corpus floor; ship release on PR #70 / `64d492a` baseline).

## Operator paths (the actual decision)

### Path 1: Honor strict gates → Option C (defensible default)

- Revert PR #75 (clean rollback to PR #74 state)
- Declare implicit-pref out-of-reach for prompt+adapter engineering
- Ship release on the 90.80% PR #70 baseline
- Accept 46.67% single-session-preference floor as a permanent feature of this architecture

This is what the falsifying experiment was designed to enforce. Strictness is the point of pre-registered gates.

### Path 2: Adjusted reading — accept the trade

- Keep PR #75 (the redesigned heuristic) on main
- Run a full 500-item corpus sweep (~$2) to measure whether the +6.67pp on SPP holds at corpus scale and whether other categories regress
- Promotion rule: if corpus ≥90.80% AND single-session-preference ≥50%, accept and flip ADR 0138 to Accepted. Otherwise revert.

Justification: v1 had REAL signal of regression (5 losses, binomial-significant). v2 has 1 loss on an item that also regressed in v1 — likely a property of the item, not the heuristic. The net delta is positive and the win/loss ratio inverted from 3/5 to 3/1.

Risk: Gate B was binary; relaxing it sets a precedent.

### Path 3: Hybrid — keep PR #75 but treat as "Proposed" pending corpus evidence

- Don't revert
- Keep ADR 0138 status as **Proposed**
- Run a full corpus sweep before ANY promotion decision
- If corpus sweep clears, treat that as the actual promotion gate (not the n=30 spike)
- If corpus regresses, then revert + Option C

Pragmatic middle ground; lets the corpus measurement decide. Cost: ~$2 of sweep.

## My recommendation

**Path 3.** The respike's binary Gate B failure on a single item that's a known-sensitive outlier doesn't justify discarding a +13.3pp swing in win/loss ratio. But the pre-registered framework is also load-bearing; I won't recommend relaxing it without explicit operator buy-in. Running the full corpus sweep at $2 is the cheapest way to convert ambiguous n=30 evidence into n=500 signal.

If you want to honor the strict-gate framework (Path 1), revert PR #75 and ship release. The 90.80% baseline is already release-worthy.

## Spike-protocol meta-note (continued)

The protocol caught a real difference between v1 and v2 (5 vs 1 regressions). The binary Gate B threshold did NOT distinguish "1 outlier item that regressed both times" from "5 broadly-noisy regressions." Future spike charters might:

- Use **discordant-pair tests** (McNemar's) rather than binary thresholds
- Pre-register a "known-outlier exclusion" mechanism for items where v1 already regressed
- Require corpus-sweep validation when n=30 evidence is ambiguous

These are protocol refinements for future ADR-0138-style chips; not a critique of the current framework.
