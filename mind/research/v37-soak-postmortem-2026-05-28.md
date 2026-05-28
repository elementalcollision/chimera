# v37 fan-out micro-soak postmortem — CONVERGES

**Date**: 2026-05-28
**Soak branch**: `chimera-soak/v37-2026-05-28-1703`
**Soak worktree**: `../chimera-soak-v37-2026-05-28-1703`
**Charter**: classify FIVE LoCoMo F2 temporal-reasoning regression items (sort-first); commit the note
**Predecessors**: v36 single-item soak (CONVERGES, [PR #117](https://github.com/elementalcollision/chimera/pull/117)); v37 runner ([PR #120](https://github.com/elementalcollision/chimera/pull/120)); phase-1 sentinel fix ([PR #118](https://github.com/elementalcollision/chimera/pull/118)); scope-check branch-prefix fix ([PR #119](https://github.com/elementalcollision/chimera/pull/119))

## Outcome: **CONVERGES**

All four positive markers from the charter hit on the first attempt:

- Research note landed at `mind/research/v37-locomo-temporal-5-item-classification.md` (6.4 KB)
- Exactly **5 paragraphs** with the locked heading pattern `## Item N: <item_id> → <label>`
- Ends with `## READY-FOR-REMEDIATION` and the summary line `Classified items conv-26::qa14..conv-41::qa45 as H2, H2, H2, H1, H1. R1 — no code change.`
- Phase-1 sentinel fired correctly (`soft_sentinel_deliverable_landed`); phase 2 committed `b3d14f2 [agent] classify items conv-26::qa14..conv-41::qa45 as H2,H2,H2,H1,H1` with exactly one file in the diff
- Pre-commit scope check (ADR 0146) verdict: **allow** — `R1`, `no_code_change`, matched the v37 design note (not a stale one)

**Operational verdict**: v36's atomic-scope hypothesis ([PR #112](https://github.com/elementalcollision/chimera/pull/112)) generalizes to N=5 fan-out within a single ACT invocation. Substrate is ready for non-trivial autonomous work.

## Substantive layer

### 5-item classification table

| # | item_id        | label | one-line summary |
|---|----------------|-------|------------------|
| 1 | conv-26::qa14  | H2    | Caroline counseling counterfactual — F1 confident, F2 hedges; same-conv retrieval certain; context-budget dilution |
| 2 | conv-26::qa22  | H2    | Caroline children's bookshelf (Dr. Seuss bridge inference) — F1 makes bridge, F2 declines under truncation |
| 3 | conv-26::qa46  | H2    | Melanie allyship inference — F1 chains pride/encouragement evidence, F2 fragments under truncation |
| 4 | conv-26::qa81  | H1    | Caroline move-back-home — F2 claims total information absence; consistent with relevant session being crowded out of top-8 |
| 5 | conv-41::qa45  | H1    | John move-to-another-country — F2 claims total information absence; same retrieval-crowdout pattern |

The agent's H1-vs-H2 distinction is principled: H2 is assigned when F2 produces **hedging on visible evidence** (items 1–3); H1 is assigned when F2 produces a **total-information-absence claim** (items 4–5). The note states this distinction explicitly in items 4 and 5 ("H2 cannot explain a total loss of the relevant session"). This is not pattern-matching; this is an evidentiary criterion applied consistently across the fan-out.

Label distribution **3× H2, 2× H1** rules out the "agent has a default" failure mode — would have been a CONFABULATES signal at all-H2 or all-H1.

### Item #1 consistency check vs v36 — **CONSISTENT (textbook)**

**v36 paragraph (commit `9cfb644`, verbatim from v36 postmortem)**:
> F1 answered correctly with a concrete "likely no" by grounding in Caroline's expressed gratitude for the support she received and concluding that without it, her motivation would not have developed the same way. F2 answered with hedging ("does not provide a direct answer... uncertain"), despite the fact that the same conversation material was available. Since F1 (no retrieval, full session) used the same answerer model (`gpt-4o-mini`) and gave a confident, correct answer, the F2 failure is not a retrieval-distractor problem (H1) — the relevant session was almost certainly selected, as the question is clearly about Caroline and the conversation is about Caroline. Nor is it a category-fundamentals problem (H3) because F1 *did* succeed at this exact temporal counterfactual without the full session sequence; the answerer can do this kind of reasoning with the right context. The most plausible explanation is H2: when top-k=8 truncated the answerer's context, the temporal-anchoring signal (Caroline's gratitude for past support → motivation linkage) was diluted by the other sessions, causing the answerer to retreat to epistemic hedging rather than committing to the counterfactual inference that F1 successfully made.

**v37 paragraph (commit `b3d14f2`, verbatim)**:
> F1 answered with a confident counterfactual inference ("Caroline's desire to pursue counseling is deeply rooted in the support she received; if she hadn't received that support, her motivation would have been diminished"). F2 retreated to hedging ("does not provide a direct answer… uncertain if she would have developed the same passion"), despite the same conversation material being available. Both runs used the same `gpt-4o-mini` answerer — so H3 (category-fundamentals) is ruled out by F1's success at this exact temporal-counterfactual question. H1 (retrieval-distractor) is implausible: the question is explicitly about Caroline and the conversation is centrally about Caroline, so the relevant session was almost certainly in the top-8. The most parsimonious explanation is H2: when top-k=8 truncated the answerer's context, the temporal-anchoring signal (gratitude for past support → current motivation) was diluted by the other seven sessions, causing the answerer to default to epistemic hedging rather than committing to the inference F1 successfully made.

**Comparison**:
- **Label**: both H2 — **same**
- **Evidence chain**: both cite (a) Caroline's gratitude for past support, (b) F1's confident counterfactual vs F2's hedging on the same conversation, (c) elimination of H3 via same-answerer F1 success, (d) elimination of H1 via clear topical anchoring, (e) H2 as parsimonious explanation under top-k=8 dilution — **same five evidentiary moves in the same order**
- **F2 quoted phrasing**: v36 quotes `"does not provide a direct answer... uncertain"`; v37 quotes `"does not provide a direct answer… uncertain if she would have developed the same passion"` — **same F2 source text**, v37 quotes one fragment longer
- **F1 paraphrase**: v36 emphasizes "likely no" + "without it her motivation would not have developed"; v37 emphasizes "deeply rooted in the support received" + "motivation would have been diminished" — **same semantic content, different surface paraphrase**

This is a strong substrate-stability signal: same input, two runs nine hours apart, same answer with the same reasoning, expressed in independently-generated prose. The agent is not verbatim-copying v36's text (the surface wording differs throughout); it is independently regenerating the same defensible diagnosis from the same grounded evidence.

## Operational layer (per-guard verdicts)

| Guard | PR | Verdict | Evidence |
|---|---|---|---|
| ADR 0141 detector (worktree drift) | [#103](https://github.com/elementalcollision/chimera/pull/103) | **PASS** | Preflight `chimera doctor` correctly flagged the throwaway preflight worktree; soak ran from secondary worktree without thread-affinity issues |
| SQLite thread-affinity fix | [#105](https://github.com/elementalcollision/chimera/pull/105) | **PASS** | 148 cycles executed from secondary worktree, zero SQLite errors in `state/chimera.db` |
| Scope check — design-note selection | [#119](https://github.com/elementalcollision/chimera/pull/119) | **PASS** (new) | `state/scope_check_events.jsonl` records `design_note: v37-locomo-temporal-5-item-classification.md` — the v37 note, not a stale v34/v36 one. **This is the first operational validation of the branch-prefix fix.** |
| Pre-commit scope check (ADR 0146) | [#106](https://github.com/elementalcollision/chimera/pull/106) | **PASS** | Verdict `allow`, recommendation `R1` with `no_code_change=true`, staged paths exactly `[mind/research/v37-locomo-temporal-5-item-classification.md]` |
| Forward-progress watchdog | [#109](https://github.com/elementalcollision/chimera/pull/109) | **PASS (silent)** | Soak converged in 3 iters total; watchdog had no opportunity to fire |
| Task-completion watchdog | [#113](https://github.com/elementalcollision/chimera/pull/113) | **PASS (silent)** | Sentinel fired before completion watchdog became relevant |
| ACT-budget enforcement | follow-up | **PASS** | `state/phase_timings.json` shows act phase = 88.65s (well under 240s default) |
| Phase-1 soft-sentinel | [#118](https://github.com/elementalcollision/chimera/pull/118) | **PASS** (new) | Phase 1 ended at iter 2 via `soft_sentinel_deliverable_landed`; phase 2 ended at iter 1 via the same sentinel. **First operational test of PR #118 — works as designed.** |
| wiring_coordinator (correctly silent) | [#111](https://github.com/elementalcollision/chimera/pull/111) | **PASS (silent)** | No INBOX prose referenced a wiring_coordinator; honest documentation held |

Two guards (PR #118, PR #119) were validated operationally for the first time in this run; both passed.

## Comparison to v36

| Metric | v36 (N=1) | v37 (N=5) | Notes |
|---|---|---|---|
| Wall time | ~19 min | ~10 min | v37 **faster** despite 5× more items — phase-1 convergence in 2 iters vs v36's longer investigation; soft-sentinel cut both phases short |
| Total spend | $0.24 | $0.14 | v37 cheaper in absolute terms |
| Phase-1 iters | several | 2 | Sentinel triggered earlier |
| Phase-2 iters | 1 | 1 | Both converged in single commit cycle |
| Per-item cost | $0.24 / item | **$0.028 / item** | ~8.6× amortization from fan-out — extremely strong amortization signal |
| ACT-budget cancellations | 0 | 0 | Per `state/phase_timings.json`: act=88.65s, far below 240s cap |
| Items classified | 1 (H2) | 5 (3× H2, 2× H1) | Label diversity rules out default-label confabulation |
| Commit shape | 1 file, 1 commit | 1 file, 1 commit | Both atomic |

The per-item cost drop from $0.24 → $0.028 is the headline operational finding. v36 was a load-bearing convergence test; v37 demonstrates that the substrate amortizes fixed overhead (loop setup, phase transitions, sentinel arming) effectively across a fan-out workload. This is what "ready for non-trivial autonomous work" means in dollar terms.

## Recommended next chip

**Charter v38 with N=10 (next 5 items, conv-41::qa45+1 through item #10 of the 19-item regression set).**

Rationale:
- Item-#1 consistency verified across two runs — substrate produces stable, defensible diagnoses on the same input
- Per-item cost amortization (~$0.03/item) makes a 10-item or 19-item run financially trivial (~$0.30–$0.55 projected)
- Wall-time projection for N=10 is well within the soak harness's 240s ACT cap given v37's 88s ACT phase
- The remaining 14 items of the 19-item regression set are the substantive deliverable for the F2 hybrid-retrieval ablation follow-up; converging on N=10 keeps the work moving without risking a too-large fan-out

Skip directly to N=19 only if the operator wants to compress the schedule; the conservative ladder is N=5 → N=10 → N=19. **Do not charter v38 from this chip — operator's call.**

## Honest disclosures

- **Three of the soft-sentinel passes are by design, not surprise**: the runner is explicitly built to short-circuit on deliverable landing. The convergence signal is "the deliverable matches the locked shape", not "the loop ran for N iterations." This is the intended atomic-scope discipline.
- **The H1-vs-H2 distinction is not externally validated**. The classifications are *defensible* given the F1/F2 JSONL evidence the agent had access to, but "defensible" is not "correct." Confirming a label as the true root cause would require counterfactual experiments (rerun item 4 with `--retrieval-top-k 16` and observe whether F2 produces hedging rather than information-absence). v37's scope intentionally does not chase this.
- **Item-#1 stability is across two runs, not many**. We have shown the substrate produces the same answer twice. We have not shown it produces the same answer reliably across, say, 20 invocations. A consistency-investigation chip could be useful before scaling to 100+ classifications if that's ever charted, but is **not** a prerequisite for v38.
- **The "first sentinel target" log line points at the wrong path** (`locomo-f2-retrieval-ablation-2026-05-27.md` instead of the v37 deliverable). This is a cosmetic log-line bug in the runner; the soft-sentinel arming line correctly targets the v37 file and is what the runner actually enforces. Worth a small follow-up chip but does not affect correctness.
- **Per-item cost is amortized fixed overhead, not a true per-item rate**. Larger fan-outs may surface real per-item cost growth; the $0.03/item figure should be treated as an upper bound on what v38 might cost, not a per-item linear-cost prediction.

## Discipline notes

- Operator-gated merge per standing rule
- Postmortem PR opens with a single file (`mind/research/v37-soak-postmortem-2026-05-28.md`)
- Soak worktree (`../chimera-soak-v37-2026-05-28-1703`) and branch (`chimera-soak/v37-2026-05-28-1703`) are untouched; operator can inspect or remove
- The v37 deliverable commit (`b3d14f2`) sits on the soak branch only; it is **not** merged anywhere — that's the operator's call for v38 charter
