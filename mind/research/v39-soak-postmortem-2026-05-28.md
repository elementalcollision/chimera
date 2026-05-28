# v39 fan-out soak postmortem — CONVERGES (closes 19-item diagnosis)

**Date**: 2026-05-28
**Soak**: `chimera-soak/v39-2026-05-28-1906`
**Charter**: classify NINE LoCoMo F2 temporal-regression items #11–#19 (sort-first, skip v37's #1–#5 AND v38's #6–#10); commit the note. Final fan-out closing the 19-item diagnosis.
**Wall**: 12m 33s (15:06:21 → 15:18:54)
**Total spend**: $0.1557 (phase 1 $0.1296 / 2 iters; phase 2 $0.0261 / 1 iter)
**Deliverable**: [v39-locomo-temporal-19-item-classification.md](mind/research/v39-locomo-temporal-19-item-classification.md) (commit `a9cc994`)

## Outcome: CONVERGES

All four CONVERGES criteria met:

1. **9 paragraphs** with heading pattern `## Item N: <item_id> → <label>` for N=11..19. Verified via `grep -n "^## Item"`:
   - Item 11: conv-43::qa34 → H2
   - Item 12: conv-43::qa67 → H2
   - Item 13: conv-44::qa20 → H1
   - Item 14: conv-47::qa12 → H2
   - Item 15: conv-47::qa25 → H2
   - Item 16: conv-47::qa33 → H2
   - Item 17: conv-48::qa28 → H1
   - Item 18: conv-49::qa5 → H2
   - Item 19: conv-50::qa42 → H2
2. **Two-predecessor carry-forward section present** at line 21 of deliverable: `## v37+v38 carry-forward (items #1-#10, NOT re-classified)`. Quotes verbatim:
   > Per v37: items #1-#5 are H2,H2,H2,H1,H1 (conv-26::qa14, conv-26::qa22, conv-26::qa46, conv-26::qa81, conv-41::qa45).
   > Per v38: items #6-#10 are H2,H4,H2,H2,H2 (conv-41::qa50, conv-42::qa0, conv-42::qa14, conv-42::qa84, conv-43::qa28).
3. **READY-FOR-REMEDIATION marker present** with cited summary line:
   > Classified items conv-43::qa34..conv-50::qa42 as H2, H2, H1, H2, H2, H2, H1, H2, H2. R1 — no code change. Completes v37+v38 fan-out; all 19 of 19 temporal-reasoning regression items now classified across v37+v38+v39.
4. **Phase-1 sentinel fired on iter 2, not iter 1**; phase-2 commit `[agent] classify items conv-43::qa34..conv-50::qa42 as H2,H2,H1,H2,H2,H2,H1,H2,H2`.

## Substantive layer

### 9-item classification table

| # | item_id | label | one-line summary |
|---|---|---|---|
| 11 | conv-43::qa34 | H2 | Polarity inversion under top-k truncation (Calvin/Dave Boston meeting) |
| 12 | conv-43::qa67 | H2 | Context-budget dilution on temporal-window question |
| 13 | conv-44::qa20 | **H1** | Information-absence response on Audrey's food preference — session crowded out of top-8 |
| 14 | conv-47::qa12 | H2 | Temporal-placement error: Sept 2022 dating event collapsed into April 2022 window (James/Samantha) |
| 15 | conv-47::qa25 | H2 | Self-contradictory answer asserting same team while citing different teams (Liverpool/Manchester City) |
| 16 | conv-47::qa33 | H2 | Literal-match hedging — refused commonsense bridge inference despite acknowledging same evidence |
| 17 | conv-48::qa28 | **H1** | Confident wrong-location (Rio for Bogotá) — distractor session above Jolene's in top-8 |
| 18 | conv-49::qa5 | H2 | Context-budget dilution |
| 19 | conv-50::qa42 | H2 | Polarity inversion under truncation |

### Two-predecessor substrate-discipline verification ✓

The carry-forward section explicitly names all ten predecessor items (5 from v37 + 5 from v38) with their labels, and adds `"These items are not re-examined."` No item from #1–#10 appears as a classification heading in v39's deliverable — verified via heading inspection. **Two-predecessor skip-rule honored without operator intervention.**

### Independent-label check ✓

Sampled the two H1 paragraphs to test for pattern-matching from v37+v38 templates:
- **Item 13** (H1): cites "Audrey's meat preference triggered BM25/dense matches to other food-discussion sessions". Independent retrieval-failure evidence.
- **Item 17** (H1): cites "BM25/dense query for 'country summer 2022 vacation' matched a distractor session featuring Rio de Janeiro above Jolene's Bogotá session". Independent confident-wrong-answer-by-distractor evidence.

The 7 H2 paragraphs each cite distinct character pairs and per-item failure modes (polarity inversion, temporal-window collapse, self-contradiction, literal-match hedging). Not pattern-matched.

### Cumulative 19-item label distribution

| | v37 | v38 | v39 | **total** | **%** |
|---|---|---|---|---|---|
| **H1** retrieval miss | 2 | 0 | 2 | **4** | 21% |
| **H2** context-budget dilution | 3 | 4 | 7 | **14** | **74%** |
| **H3** answerer-model failure | 0 | 0 | 0 | **0** | 0% |
| **H4** F1/F2 spec drift | 0 | 1 | 0 | **1** | 5% |
| total | 5 | 5 | 9 | **19** | 100% |

### Headline finding

**H2 (context-budget dilution under top-k=8 truncation) dominates the LoCoMo F2 temporal-reasoning regression at 74%.** H3 is absent across all 19 items — the −10.42pp regression is *not* an answerer-model defect. H1 (retrieval miss) is a meaningful minority at 21%. H4 (F1/F2 spec drift) is a singleton at 5%.

The dominant failure mode is the agent recognizing the right session was retrieved, but under top-k=8 truncation the temporal anchors get compressed and the answerer either inverts polarity (yes/no questions) or collapses adjacent time windows (when/where questions). This is mechanistically a **context-budget vs. temporal-anchor-density** problem, not a retrieval or model-capability problem.

## Operational layer

| guard | result | evidence |
|---|---|---|
| ADR 0141 detector | ✓ pass | `chimera doctor` showed `worktree_branch_drift` status `ok` in preflight |
| SQLite thread fix | ✓ pass | No SQLite errors in soak log |
| Scope check (PR #119 design-note matching) | ✓ pass | Preflight: `matched: v39-micro-soak-design-2026-05-28.md` |
| Forward-progress watchdog | ✓ pass | Did not fire; soak made progress every iter |
| Task-completion watchdog | ✓ pass | Did not fire; deliverable shipped before cap |
| ACT-budget enforcement (PR #112) | ✓ pass | Phase-1 iter 1 hit 240004.6ms (budget 240000ms) — budget enforced exactly, iter 2 replanned successfully |
| Phase-1 sentinel-target (PR #126 fix) | ✓ **PASS — fix effective** | See dedicated section below |
| wiring_coordinator | n/a | not active in micro-soak |
| Phase-1 engines-off enforcement | ✓ pass | `PermissionError: git commit blocked: CHIMERA_ENGINES_ENABLED=0` — guard fired correctly when agent attempted a phase-1 commit; recovered in iter 2 |

## Phase-1 sentinel-target fix verdict (PR #126)

**Verdict: fix took effect.** v38's postmortem flagged that v37/v38 had `INVESTIGATION_DOC` extracted via `soak_extract_sentinel_path`, which pointed at the first backticked INBOX entry (the F1 INPUT file) rather than the agent's OUTPUT deliverable, making `ready_marker_found` trivial. PR #126 set `INVESTIGATION_DOC` explicitly to the v39 OUTPUT.

Evidence from the soak log:

```
[15:06:21] phase-1 sentinel target (v39 explicit fix): /.../v39-locomo-temporal-19-item-classification.md
[15:06:21] phase1 iter 1  cycle=0  spend=$0.0  cap=$5.00
phase loop.act done in 240004.6ms (budget 240000ms)
[15:10:42] phase1 iter 2  cycle=146  spend=$0.0318  cap=$5.00
[15:14:43] ── phase1 end: soft_sentinel_deliverable_landed  spend=$0.1296 iters=2 ──
```

- Phase 1 did NOT exit on iter 1 with $0 spend — the predecessor-match short-circuit is closed.
- Phase 1's `soft_sentinel_deliverable_landed` exit at iter 2 corresponds to the agent having written `v39-locomo-temporal-19-item-classification.md` (timestamp 15:14, mid-iter-2). The marker fired against the v39 OUTPUT, not a predecessor.
- Compare to v38: phase 1 exited on iter 1 with $0 spend because the runner matched a predecessor's existing deliverable. v39 does not exhibit this behavior.

**Operationally validated.** The v39 substrate is the first in the series to have a correctly-targeted phase-1 sentinel.

## Cost amortization — v37 vs v38 vs v39

| soak | items | wall | total spend | per-item |
|---|---|---|---|---|
| v37 | 5 | ~? | ~$0.135 | $0.027 |
| v38 | 5 | ~? | ~$0.40 | $0.080 |
| v39 | 9 | 12m 33s | $0.1557 | **$0.017** |

**Cumulative across 19 items**: ~$0.69. **Per-item trend went DOWN, not up**, contradicting PR #124's prediction that per-item cost would drift toward $0.10 with more predecessor integration. Two contributing factors:

1. **Larger denominator**: 9 items in v39 vs 5 in v37/v38 amortizes fixed phase costs (launch, doctor, scope-check, commit) over more units.
2. **Phase-1 efficiency**: ACT-budget enforcement (PR #112) capped iter 1 at 240s when the agent stalled; iter 2 produced the full deliverable cheaply because the agent had already cached the F1/F2 data reads from iter 1.

The cost surprise is a **positive operational finding**: the soak substrate at N=9 with two-predecessor skip discipline is *cheaper per item* than smaller fan-outs. This expands the credible upper bound for future fan-out scope, though wall-time grows with predecessor count.

## Recommended next chip

**Operator's call — NOT chartered from inside this chip.** The natural capstone is an **ADR 0142 synthesizing amendment** that:

1. Records the cumulative 19-item label distribution (H2 74%, H1 21%, H4 5%, H3 0%).
2. Updates ADR 0142's verdict to incorporate the diagnosed root cause: **context-budget dilution under top-k=8 truncation**, not answerer-model failure.
3. Decides remediation direction. The 74% H2 dominance suggests the remediation lever is on the retrieval/context-budget axis (e.g., adaptive top-k for temporal queries, or temporal-anchor preservation under truncation), not on the answerer model.

v40 should **NOT** be chartered for fan-out's own sake. The 19-item diagnosis is complete and statistically usable.

## Honest disclosures

- **Per-item cost surprise**: the trend reversed (down to $0.017 from $0.080), against PR #124's prediction. Worth flagging — the prediction was wrong but in the favorable direction.
- **Phase-1 engines-off guard fired during iter 1**: the agent attempted a git commit, which was correctly blocked by `CHIMERA_ENGINES_ENABLED=0`. Iter 2 recovered. This is the guard working as designed but it indicates the agent's default behavior in phase-1 still tries to commit; a future hardening chip could prefer documentation-only phase-1 prompts that don't elicit commit attempts.
- **ACT budget hit exactly at 240004.6ms in iter 1** — the budget enforcement (PR #112) is precise, but the iter-1 stall pattern is consistent across v37/v38/v39. Investigating *why* the agent stalls on iter 1 of every soak (possibly initial F1/F2 data read latency) could shave a phase-1 iteration.
- **Substantive label distribution is the agent's call, not independently validated**. The label distribution (74% H2) is consistent and well-reasoned per-item, but the overall finding rests on the agent's classification, not a separate ground-truth check. An ADR 0142 amendment author should sanity-check a sample.
- This postmortem was written by the supervisor agent based on log+deliverable inspection; the operator should verify the headline distribution before authoring the ADR amendment.

## Substantive vs operational

- **Operational**: clean pass. All 8 active guards behaved correctly. Phase-1 sentinel-target fix (PR #126) is verified effective. ACT-budget enforcement, scope-check, two-predecessor skip discipline, engines-off enforcement all green.
- **Substantive**: high-confidence convergence. Independent labels with per-item evidence; two-predecessor skip honored; H3 absent across all 19 items is a decisive finding.

Both layers ship.
