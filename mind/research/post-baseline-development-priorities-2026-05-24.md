# Post-baseline development priorities — recommendation for the main session soak (2026-05-24)

**Audience**: the autonomous main session soak that picks up chips from `mind/`.
**Purpose**: convert the LongMemEval smoke baseline (captured in [PR #56](https://github.com/elementalcollision/chimera/pull/56)) into an ordered, charter-disciplined chip queue. Each entry below is a candidate soak chip — scoped, sized, and with a falsifiable success metric tied to the baseline numbers.
**Charter discipline reminder** (from the PR #41 close-out): every chip below assumes ADR-Proposed-status-until-validated, locked surface, named follow-ups. The soak should NOT implement everything in one chip.

---

## Executive summary

The smoke baseline showed a clean split:

| Cluster | Categories | Smoke accuracy |
|---|---|---:|
| **Single-session lexical retrieval** | single-session-user, single-session-assistant, temporal-reasoning | 100% (15/15) |
| **Cross-session synthesis** | multi-session, knowledge-update, single-session-preference | 20% (3/15) |

Three failure modes drive the 80-percentage-point gap. Two are **prompt-engineering chips** (cheap, high leverage). One is a **retrieval-architecture chip** (Phase 4 #6.b, harder). Doing the prompt fixes first is correct because they cost ~$0 to validate and would likely move multi-session and knowledge-update to ~60–80% before retrieval becomes the bottleneck.

---

## Diagnosis: three failure modes

Per-item review of the 12 wrong answers in the smoke set (see [baseline note §"Per-item failure attribution"](./longmemeval-baseline-2026-05-24.md#per-item-failure-attribution-smoke-only-observations)):

### Failure mode A — "anchored on the most recent session"

**Categories affected**: multi-session (4/4 wrong), knowledge-update (4/4 wrong).

**Symptom**: the dialectic-API prompt assembled by the adapter today concatenates every session's turns into one big markdown blob (`mind/peers/self.md` `## History` section). The model reads the whole thing but the prompt doesn't *direct attention* to anything cross-session. Models default to the most recent session because that's the strongest local prior.

**Root cause**: prompt engineering, not retrieval. The history *is* in the prompt; the prompt doesn't tell the model how to use it.

### Failure mode B — "extracted info but didn't apply the preference"

**Categories affected**: single-session-preference (4/4 wrong).

**Symptom**: model correctly identified the user's preference (vegetarian, prefers concise responses, etc.) but the *answer it generated* didn't follow that preference. The preference text is in the prompt; the answer ignored it.

**Root cause**: prompt engineering. The dialectic template asks "answer the question" without an explicit "follow the user's stated preferences when answering" instruction.

### Failure mode C — "6 empty hypotheses from o4-mini"

**Categories affected**: spread across all categories.

**Symptom**: 6 of 30 items returned empty `hypothesis` field from `openai/o4-mini`. Reasoning-token budget exhaustion at `max_tokens=512` on deep histories.

**Root cause**: parameter tuning, not algorithm. Raising the budget to 2048 (or making the adapter retry-with-larger-budget on empty) likely recovers most.

---

## Tier 1 — cheap, high-leverage (ship first)

These are the right chips to start with: they cost almost nothing to implement and each has a falsifiable score delta tied to specific baseline categories.

### Chip T1.1 — Token-budget recovery for `--answer`

**Maps to**: failure mode C.
**Expected delta**: +6 hypotheses (out of 30); category-distributed; ~+10pp overall on smoke.
**Files** (3): `chimera/cli.py` (`_build_openrouter_answer_fn` → raise `max_tokens` to 2048; add `--answer-max-tokens` flag), `tests/test_longmemeval.py`, no ADR (parameter tuning).
**Charter notes**: trivial. Single ADR-less PR. Validate by re-running the smoke; count empty hypotheses → near-zero.

### Chip T1.2 — Temporal-aware dialectic prompt (closes Failure mode A)

**Maps to**: failure mode A (multi-session + knowledge-update at 20%).
**Expected delta**: +0–60pp on those two categories. Conservative estimate +30pp.
**Files** (4): `chimera/a2a/dialectic.py` (extend `_DIALECTIC_PROMPT` with explicit cross-session instructions: "When the question requires information from multiple sessions, integrate facts across the entire history. When a fact stated in an earlier session is contradicted by a later session, prefer the later session."), `tests/test_dialectic.py`, `docs/adr/0136-temporal-aware-dialectic.md` (Proposed), `docs/adr/README.md`.
**Charter notes**:
- ADR-Proposed-until-validated. Promotion gate: re-run smoke, multi-session and knowledge-update each move by ≥20pp.
- Out of scope: rewriting the answer-side prompt (we only own the *assembled grounding* layer; the answerer model decides how to use it). The chip's surface is the dialectic template string + one new test.
- This is a single-file behavior change; resist scope creep.

### Chip T1.3 — Preference-aware dialectic prompt (closes Failure mode B)

**Maps to**: failure mode B (single-session-preference at 20%).
**Expected delta**: +40–60pp on single-session-preference.
**Files** (4): `chimera/a2a/dialectic.py` (add a "When the user has stated preferences about how they want to be answered, honor those preferences in your response." line to the dialectic prompt), `tests/test_dialectic.py`, `docs/adr/0137-preference-aware-dialectic.md` (Proposed), `docs/adr/README.md`.
**Charter notes**:
- Can be combined with Chip T1.2 if both ship in the same PR. Same surface, same risk profile. I'd prefer separate PRs for cleaner regression attribution (each prompt change moves a known category).
- Promotion gate: single-session-preference moves by ≥20pp on smoke.

### Chip T1.4 — Full 500-item sweep (replaces smoke baseline)

**Maps to**: smoke-scale variance noted in the baseline.
**Expected delta**: not a feature — establishes a stable baseline.
**Files** (1): `mind/research/longmemeval-baseline-2026-05-25.md` (or whatever date the soak runs it). No code changes.
**Charter notes**:
- Operator-cost is ~$1–$2 of inference + ~$0.20 grading.
- Should be run **after** Chips T1.1/T1.2/T1.3 land — the full-sweep numbers are the load-bearing baseline that Phase 4 #6.b uses as a merge gate, so capture them against the *improved* prompt.
- This is a "research note" chip (no ADR), same shape as the smoke baseline.

---

## Tier 2 — real engineering (after Tier 1)

### Chip T2.1 — Phase 4 #6.b real-embedding integration

**Maps to**: residual cross-session weakness *after* Tier 1 prompt fixes have done their work.
**Expected delta**: depends on Tier 1 outcomes. If multi-session is still <70% after Chip T1.2, hybrid retrieval is the next lever. If it's already at 80%+, defer this until the long-horizon `longmemeval_s_cleaned.json` becomes the corpus (which exposes retrieval bottlenecks the oracle set doesn't).
**Files** (~6): `chimera/embedding/__init__.py` (new), `chimera/embedding/openrouter.py` (sentence-embedding via OpenRouter), `chimera/memory/hybrid_search.py` (fill in the stubs), `tests/test_hybrid_search.py` (real-embedding path), `docs/adr/0134-hybrid-search-eval.md` (Proposed → Accepted with embedding model decision), `docs/adr/README.md`.
**Charter notes**:
- **This is the chip PR #41 tried to ship and overshot.** Reference the close-out review on PR #41 before starting. Surface should still be locked behind `CHIMERA_HYBRID_SEARCH=1`.
- Promotion gate: when enabled, on the same smoke set, multi-session must not regress; knowledge-update must improve by ≥5pp.
- Out of scope (in this chip): peer-scoped collections, CLI `--hybrid` exposure, `vec0` swap. All named in ADR 0134 follow-ups already.

### Chip T2.2 — Long-horizon sweep (`longmemeval_s_cleaned.json`)

**Maps to**: testing whether Chimera generalises from oracle (ground-truth retrieval given) to the long-horizon set (model has to find the needles).
**Files** (1): `mind/research/longmemeval-s-baseline-2026-05-XX.md`. No code changes; runs the existing adapter against a different `--items` file.
**Charter notes**:
- The `_s` set is bigger (~50K-token histories per item) and the adapter's current "write the whole history into one markdown file" ingestion will balloon the dialectic prompt past most context windows. Expect this sweep to surface real adapter limitations.
- This is the natural justification for Chip T2.1 (hybrid retrieval) — if the `_s` sweep shows the prompt is overflowing context, retrieval becomes load-bearing.

---

## Tier 3 — research-flavored (after Tier 2)

### Chip T3.1 — LoCoMo integration

**Maps to**: ADR 0123 Phase 4 #8 originally named LoCoMo as the second benchmark; deferred per [`eval-harness-2026-05-24.md`](./eval-harness-2026-05-24.md). Only worth tackling if LongMemEval saturates and we need harder signal, OR if a future Chimera capability (persona / multimodal) needs LoCoMo's testing axes.
**Files** (~6): mirror the LongMemEval adapter shape — `chimera/evals/locomo.py`, `tests/test_locomo.py`, `docs/adr/0138-locomo-integration.md`, etc.
**Charter notes**: don't do this until LongMemEval has stopped surfacing actionable signal. Otherwise it's wasted scope.

### Chip T3.2 — Deriver-style answerer (replace prompt-passthrough)

**Maps to**: ADR 0124 deriver pattern. Today's `--answer` passes the dialectic prompt to o4-mini and takes the raw text. A deriver pattern would extract typed conclusions from the assembled grounding and synthesise a structured response.
**Files**: TBD — needs its own research note first.
**Charter notes**: skip until Tier 1 + Tier 2 have run. The prompt-passthrough is at 60% overall; deriver-style would matter if we're trying to get from 80% → 90% and prompt engineering has hit diminishing returns.

---

## Anti-priorities (do NOT start on these yet)

These are tempting but premature:

1. **Don't rewrite `LongMemEvalAdapter.ingest_history` to do chunked-per-session ingest.** The current "one big markdown file" approach is fine for oracle-set sized histories; it only breaks at `_s`-set scale. Wait until Chip T2.2 surfaces the actual problem.
2. **Don't add a CLI verb for the grader (`chimera evals longmemeval-grade`).** The ad-hoc `/tmp/chimera-baseline/grade.py` from the baseline run worked. Promote it to a CLI verb only if the grading step recurs ≥3 times — otherwise it's premature scope.
3. **Don't tune RRF k or hybrid-search alpha before Chip T2.1.** Tuning has nothing to tune until the vector half exists.
4. **Don't pivot to LoCoMo "for variety".** Failure modes on LongMemEval are concrete and actionable; LoCoMo would dilute the signal.
5. **Don't promote ADR 0134 (hybrid search) to Accepted until Chip T2.1 ships.** Status stays Proposed until the integration validates the vendor decision in-situ. This is locked.
6. **Don't add reasoning-effort heuristics to the adapter** (e.g. "use o4-mini for hard questions, gpt-4o-mini for easy"). The smoke shows o4-mini is fine across categories. Selection-heuristic chips are premature optimisation.

---

## Suggested chip sequence for the soak

```
[T1.1 token budget]  ─┐
                      ├──[T1.4 full sweep]──┐
[T1.2 temporal]      ─┤                     │
                      │                     ├──[T2.1 hybrid retrieval]──[T2.2 long-horizon]──[T3.x]
[T1.3 preference]    ─┘                     │
                                            │
                                  promotion gate:
                                  full-sweep numbers
                                  replace smoke numbers
```

**Critical path**: T1.1 → (T1.2 ‖ T1.3) → T1.4 → T2.1.

**Total Tier 1 effort**: ~3 small PRs + 1 sweep run. Total inference cost: ~$3–$5 (one smoke per chip + one full sweep). All Tier-1 PRs should ship within a few days of soak time.

**Tier 1 success criterion**: when the full-sweep baseline post-Tier-1 shows ≥75% overall (up from 60% smoke), the cross-session-synthesis "cliff" is mitigated and Phase 4 #6.b's expected impact is now bounded enough to justify the engineering cost.

---

## What this doc is NOT

- Not an ADR. Decisions live in ADRs; this is a queue.
- Not a charter. Each chip above needs its own charter when the soak picks it up.
- Not a promise of score deltas. The "+30pp" / "+40pp" estimates are heuristic priors based on the failure-mode read; the actual delta is what the next sweep measures.
- Not a substitute for review. Every chip ships as a PR with the same review gates as PR #41 enforced.

## References

- [`mind/research/longmemeval-baseline-2026-05-24.md`](./longmemeval-baseline-2026-05-24.md) — the smoke baseline this doc derives from (lands with [PR #56](https://github.com/elementalcollision/chimera/pull/56)).
- [`mind/research/eval-harness-2026-05-24.md`](./eval-harness-2026-05-24.md) — research note that locked LongMemEval-first.
- ADR 0133 — Dialectic API (the prompt-template surface Chips T1.2 + T1.3 modify).
- ADR 0134 — Hybrid search vendor decision (Chip T2.1 closes this loop).
- ADR 0135 — LongMemEval adapter (the surface every chip above measures against).
- [PR #41 close-out review](https://github.com/elementalcollision/chimera/pull/41) — charter-discipline lesson Chip T2.1 must honor.
