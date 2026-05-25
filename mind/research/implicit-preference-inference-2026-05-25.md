# Implicit preference inference — failure taxonomy (2026-05-25)

**Purpose**: Diagnostic-only investigation of the residual single-session-preference cliff at 46.67% (14/30) from the post-T1.5 sweep ([PR #70](https://github.com/elementalcollision/chimera/pull/70)). single-session-preference is the only category not clearing 75% and is the natural Tier-2B candidate. This note follows [PR #68's methodology](./temporal-reasoning-regression-2026-05-25.md): pull the wrong items, build a taxonomy, **falsify the prompt-wording hypothesis** before recommending an intervention.

Companion to:

- [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) — the baseline this note dissects.
- [`temporal-reasoning-regression-2026-05-25.md`](./temporal-reasoning-regression-2026-05-25.md) — the investigation template (grounding-vs-wording diagnosis).
- [ADR 0137 — Preference-Aware Dialectic](../../docs/adr/0137-preference-aware-dialectic.md) — T1.3's "honor stated preferences" sentence.

**No code change is shipped in this chip.** Output is this note + [ADR 0138 (Proposed)](../../docs/adr/0138-implicit-preference-inference.md).

---

## Headline

The 16 wrong single-session-preference items partition cleanly into four classes:

| Class | n | Description |
|---|---:|---|
| **P-HEDGE** | 7 | Model returns "I don't have information on X" / "the provided notes don't include …" despite the prior session containing the user's transferable context |
| **P-GENERIC** | 6 | Model gives a generic, well-formed answer to the surface question but ignores the user's specific prior turns (e.g. their Suica card, their Brandon Flowers encounter, their lemon-poppyseed cake success) |
| **P-EMPTY** | 2 | Empty hypothesis (`caf03d32`, `6b7dfb22` — both deep-history items; 2048-token answer budget consistent with the [post-T1.5 empty-rate note](./longmemeval-baseline-post-t1.5-2026-05-25.md#empty-hypothesis-count--held-steady)) |
| **P-WRONG-TOPIC** | 1 | Model latched onto the wrong session topic (`38146c39` — cookies-question, answered with carrot-cake nut suggestions because the session mentioned both) |

**Brief's a-priori classes vs observed.** The brief proposed six classes (P1 non-canonical phrasing, P2 inferred-from-behavior, P3 inferred-from-negation, P4 inferred-from-domain, P5 grounding-content miss, P6 other). The observed dominant axis is not *how the preference is phrased* but *whether the model engages with the prior session at all* — P-HEDGE means "didn't engage," P-GENERIC means "engaged with the surface question but not the user-specific context," P-WRONG-TOPIC is a retrieval-attention failure. The brief's P1/P2/P3/P4 distinction collapses in this data because **all 14 right items and all 13 non-empty wrong items have the same task shape** — implicit, cross-topic preference transfer (see disconfirmation §below). The split is on model behavior, not preference-statement shape.

---

## Per-item table

All 16 wrong items. "Has user-specific context in session" — does the prior session contain a transferable preference signal (resource, prior choice, stated taste) that the gold answer requires? — answered Y/N from inspecting `longmemeval_oracle.json` source sessions directly.

| item_id | Class | Q (surface) | Has user-specific context? | Notes |
|---|---|---|---|---|
| 75832dbd | HEDGE | recent AI publications/conferences | Y — user is healthcare-AI researcher (deep-learning, medical imaging) | Hedged "no specific recent confs in grounding"; user's domain was inferable |
| 0edc2aef | HEDGE | hotel for Miami | Y — Seattle hotel session reveals "great views + rooftop pool + hot tub on balcony" prefs | Model said "no info on Miami hotels," didn't transfer prefs cross-city |
| 35a27287 | HEDGE | weekend cultural events | Y — user is Spanish/French language learner | Hedged "no location/real-time"; should have biased toward language exchanges |
| afdc33df | HEDGE | kitchen cleaning tips | Y — user just bought utensil holder, organized countertops | Hedged "notes focus on fixtures"; should have built on the organization theme |
| 09d032c9 | HEDGE | phone battery tips | Y — user owns portable power bank from prior turn | Hedged "no info on battery life"; should have suggested charging via the power bank |
| 57f827a0 | HEDGE | bedroom rearranging | Y — user is replacing dresser + likes mid-century modern | Hedged "no info"; full context was in the session |
| 1da05512 | HEDGE | NAS now vs wait | Y — user has storage capacity issues + reliance on external HDs | Hedged "only covers comparing NAS models" |
| d24813b1 | GENERIC | baking for colleague gathering | Y — user's lemon-poppyseed cake success | Suggested cookies + a pound cake; didn't reference lemon-poppyseed |
| 95228167 | GENERIC | guitar shopping tips | Y — user is comparing Strat vs Les Paul | Gave generic feel/sound tips; didn't anchor on the specific comparison |
| 505af2f5 | GENERIC | new coffee creamer recipe | Y — user's almond-milk/vanilla/honey + reducing-sugar goal | Suggested cinnamon-vanilla oat-milk; didn't build on user's existing recipe |
| 75f70248 | GENERIC | sneezing — is it living room? | Y — cat Luna + recent deep-clean | Gave generic dust/dander advice; mentioned cat in passing but didn't name Luna or tie to deep-clean |
| a89d7624 | GENERIC | trip to Denver | Y — Killers at Red Rocks + Brandon Flowers meeting | Gave generic Denver music venues; didn't reference user's prior Denver visit |
| 0a34ad58 | GENERIC | Tokyo transit tips | Y — Suica card + TripIt app | Mentioned Suica generically; didn't anchor on user's named tools |
| caf03d32 | EMPTY | slow cooker recipes | (n/a) | Empty — likely answer-budget exhaustion |
| 6b7dfb22 | EMPTY | painting inspiration | (n/a) | Empty — likely answer-budget exhaustion |
| 38146c39 | WRONG-TOPIC | chocolate-chip cookie advice | Y (turbinado sugar success) | Answered about carrot-cake nuts — the session mentioned both, model attended wrong subtopic |

**Every wrong non-empty item has user-specific context present in the prior session.** 13/13 = 100%. There is no item where the model "couldn't answer because the preference wasn't in grounding." This is the load-bearing observation for the diagnosis below.

---

## Disconfirmation test for the prompt-wording hypothesis

PR #68's pattern: form a falsifiable test that distinguishes "prompt phrasing is the bottleneck" from "grounding content is the bottleneck." Three independent checks.

### Test 1 — Length comparison

| Bucket | n | Median hyp length (chars) | Mean hyp length (chars) |
|---|---:|---:|---:|
| Right (14) | 14 | **502** | 455 |
| Wrong (16, incl 2 empties) | 16 | 262 | 302 |
| Wrong, non-empty (14) | 14 | ~290 | ~345 |

Wrong items are roughly **half** the length of right items at the median. Consistent with hedging shortening the answer. Not consistent with "longer ignoring-constraint answers" (that would predict wrong-items longer than right, like a verbose generic spew). This rules out a "model is over-answering and ignoring prefs" hypothesis and points toward "model is under-engaging."

### Test 2 — Right items already do the inference

The 14 right items have **the same task shape** as the wrong items: implicit, cross-topic preference transfer. Examples from the right column:

- `06878be2` — Q "accessories that complement my photography setup"; the session establishes Sony A7R IV + Godox V1; hypothesis names Sony/Godox-compatible accessories specifically. Cross-topic transfer worked.
- `1a1907b4` — Q "cocktail for upcoming get-together"; the session establishes user took a mixology class with Hendrick's gin; hypothesis names specific Hendrick's cocktails. Cross-topic transfer worked.
- `d6233ab6` — Q "high school reunion — good idea?"; session establishes debate-team + AP-economics memories; hypothesis cites them. Cross-topic transfer worked.

**If the current `_DIALECTIC_PROMPT` ("honor stated preferences") were genuinely blocking implicit-preference inference, the right items would also fail.** They don't. The prompt already permits — and demonstrably elicits — implicit preference transfer when the model engages with the prior session.

This **falsifies the prompt-wording-is-bottleneck hypothesis.** Adding "honor *inferred* preferences too" would land in a prompt that already produces this behavior 14/30 times; the failure mode is not phrase-shaped.

### Test 3 — Grounding-presence check

For each of the 13 non-empty wrong items, does the relevant user-specific signal appear in the assembled `peer_card_block`?

The adapter's [`ingest_history`](../../chimera/evals/longmemeval.py) writes **every turn of every session verbatim** into `mind/peers/self.md` under `## History`. For single-session items (n=1 haystack session per item), the prior session content is **fully present in the peer card** that `gather_dialectic_context` reads. There is no truncation pre-prompt in the current pipeline.

Spot-checked by re-reading the source sessions for `0edc2aef` (Seattle hotel prefs → Miami question), `09d032c9` (power bank → phone battery), `0a34ad58` (Suica/TripIt → Tokyo tips), `a89d7624` (Red Rocks/Brandon Flowers → Denver tips): all four have the load-bearing preference signal in the dataset's session content. Adapter writes them verbatim. **Grounding-presence is not the bottleneck either.**

This is the inverse of PR #68's temporal-reasoning finding: there, the preference signal (dates) was **absent** from grounding; here, the signal is **present** but the model fails to act on it consistently. Same investigative template, opposite diagnostic outcome.

### Diagnostic outcome

| Hypothesis | Verdict |
|---|---|
| The `_DIALECTIC_PROMPT` wording fails to elicit implicit preference inference | **Falsified** — right items demonstrate the current prompt elicits the behavior |
| The preference signal is absent from the assembled grounding (PR #69 analogue) | **Falsified** — adapter writes every turn verbatim; signal is present for 13/13 non-empty wrong items |
| The signal is present + prompt permits use, but the model's *engagement* with the prior session is inconsistent | **Consistent with the data** — 7 hedges + 6 generic answers despite full context |

**The residual is a behavior-consistency cliff, not a prompt-wording or grounding-content cliff.**

---

## What that means for an intervention

Three intervention shapes survive the diagnostic. They have different effort, different expected delta, and different risk profiles.

### Option A — Prompt extension (the brief's first suggestion)

Append one sentence to `_DIALECTIC_PROMPT`, e.g.:

> "When the user has not explicitly stated a preference but their prior turns reveal one, honor the inferred preference too."

**Expected delta**: Low. The right items show this behavior is already elicited from the current prompt. Adding the sentence may marginally reduce P-HEDGE (7 items) by making it explicit that hedging is wrong when relevant context is present, but it is not addressing the root cause (engagement consistency). PR #68's path-1 sweep (the wording-only intervention on temporal) provides the cautionary precedent: T1.2 +0.5pp from prompt wording alone.

**Risk**: Low-moderate. T1.2's regression-from-narrative-bias precedent (later traced in PR #68 to grounding, not wording) shows prompt-rewording can have unintended cross-category effects. Honest range: **-2pp to +5pp** on category, -1pp to +1pp overall.

### Option B — Adapter grounding extension (PR #69 analogue)

Surface a dedicated **`## User context`** or **`## Recent user preferences`** section in the peer card, distilled from the prior session via a simple structural pass (e.g. extract user turns matching keyword patterns: `I (have|own|like|prefer|use|bought|usually|tried) X`, plus the first user turn as topic anchor). Place it **above** `## History` so the answerer reads it before the verbatim transcript.

**Expected delta**: Moderate. This addresses both P-HEDGE (now the user's specifics are highlighted; harder to claim "no info") and P-GENERIC (the section is a checklist the answerer is more likely to honor). Does not address P-WRONG-TOPIC (which is attention/retrieval, orthogonal). Does not address P-EMPTY (answer-budget). Honest range: **+5pp to +15pp** on category, ±1pp overall.

**Risk**: Moderate. Heuristic extraction is brittle — a poor regex could surface noise that confuses the answerer. Two failure modes to guard against: (a) extracting non-preference user turns ("what's the weather?"), (b) extraction collapses to nothing on a deeply-implicit session and the section becomes empty (no harm, but no help either). Mitigated by keeping the section optional (omit if extraction yields <2 items).

**Note** — Option B is the structural analogue of PR #69's win: T1.5 took grounding content that was *technically* present (dates in `haystack_dates`) and surfaced it in a dedicated section the answerer would read. Here the content is also present (user turns in `## History`) but spread across a long transcript the answerer skims.

### Option C — Declare out-of-reach for the adapter+prompt layer

Accept the 46.67% floor as the long-term ceiling for this layer of the stack. Route the chip elsewhere:

- A **retrieval-time** intervention (semantic similarity between prior-session user turns and the new question, surfacing the top-k most-relevant user turns as a sidebar) — this is the deferred Phase 4 #6.b hybrid-retrieval scope.
- An **ingestion-time** intervention (LLM-based preference extraction stored as a structured `preferences.json` peer card; ADR 0137's referenced "follow-up — implicit preference inference" line) — heavier infra; entire new pipeline.
- Honest acceptance that single-session-preference at n=30 will jitter ±3.3pp/item even with no change, and the 16 wrong items may be near the noise floor for an 8B-class answer model treating an oracle-set adversarially-curated split.

**Expected delta**: 0pp from this chip (no change). Defers the problem.

### Charter-discipline note

The pattern that worked twice now (PR #68 → PR #69, PR #67 baseline → PR #70 +10pp) is *one falsifiable measurement at a time*. The brief flags that "n=30 single-session-preference means each individual miss is a 3.33% category swing" — a same-shape oracle-set re-sweep cannot distinguish a +5pp move from noise without paired-item analysis. Any Option A or B chip should commit upfront to **paired-item reporting** (which of the 16 specific wrong items flipped right vs which of the 14 right items flipped wrong) rather than relying on the category-aggregate move alone, given the n=30 jitter envelope.

---

## Recommendation

**Option B (adapter grounding extension), conditional on a small-N spike first.**

Reasoning:

1. The diagnostic falsifies Option A's premise (Test 2). Shipping a prompt sentence in the face of falsifying data would replay T1.2's mistake.
2. Option B is the direct structural analogue of PR #69 (the chip that just shipped a +36.85pp temporal win); the template is well-understood and the implementation cost is one ~20-line method in [`LongMemEvalAdapter.ingest_history`](../../chimera/evals/longmemeval.py:205) plus a 2-line peer-card insertion.
3. Option C is honest but defers indefinitely without a clear next-chip charter; the brief explicitly asks for a "hypothesis-test-ready plan."

The conditional: before a full 500-item sweep, run a **single-category n=30 spike** on `--subset single-session-preference` (≈3 min, well under the operator's sweep envelope) with the Option-B extraction prototype. Gate the full sweep on: (a) ≥2/16 of the named wrong items flip right, (b) no regression among the 14 right items. If the spike fails either gate, fall back to Option C and document.

**Expected post-Option-B headline if the spike clears the gate**:

| Category | Post-T1.5 | Hypothesised post-T2B |
|---|---:|---:|
| single-session-preference | 46.67% (14/30) | 55–70% (17–21/30) |
| overall | 90.80% (454/500) | 91.2–91.6% (456–458/500) |

Margin small; pair with paired-item disclosure (per charter-discipline note above) so signal isn't lost in the jitter.

---

## Cross-category check — is there spillover risk?

Option B writes a new section above `## History`. The answerer reads the peer card top-down. Possible cross-category effects:

- **temporal-reasoning** (90.23%): the `**Today's date:**` line stays at the top per PR #69 layout; the new section slots between `**Today's date:**` and `## History`. Date anchor still load-bearing — no expected regression.
- **knowledge-update** (96.15%): user preferences are mostly orthogonal to fact-updates. Low spillover risk.
- **single-session-user / -assistant** (98.57% / 100%): saturated; either category could drop a single item under noise. Worth watching.
- **multi-session** (90.23%): the section would be drawn from across multiple haystack sessions; risk of *helpful* spillover (cross-session memory is partially what multi-session tests). Could move the needle up or down.

The "any category regresses >3pp triggers rollback" rule from the post-T1.5 charter applies.

---

## Sweep metadata reused

All analysis in this note is over `/tmp/chimera-baseline-t15/results-post-t1.5-graded.jsonl` (the post-T1.5 sweep from PR #70, `main` at `14192658`). No new sweep was run. Source `longmemeval_oracle.json` consulted at `/Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json` (upstream commit `9e0b455f4ef0e2ab8f2e582289761153549043fc`).

---

## References

- [PR #66](https://github.com/elementalcollision/chimera/pull/66) — T1.3 "honor stated preferences" prompt amend.
- [PR #67](https://github.com/elementalcollision/chimera/pull/67) — post-Tier-1 baseline (80.60% overall).
- [PR #68](https://github.com/elementalcollision/chimera/pull/68) — temporal-reasoning grounding-vs-wording diagnosis (the methodology template).
- [PR #69](https://github.com/elementalcollision/chimera/pull/69) — T1.5 timestamp grounding (Option B's structural analogue).
- [PR #70](https://github.com/elementalcollision/chimera/pull/70) — post-T1.5 baseline (90.80% overall).
- [ADR 0137](../../docs/adr/0137-preference-aware-dialectic.md) — preference-aware dialectic (Accepted).
- [ADR 0138](../../docs/adr/0138-implicit-preference-inference.md) — implicit preference inference (Proposed, this chip).
