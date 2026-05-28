# v38 fan-out soak postmortem — CONVERGES

**Date**: 2026-05-28
**Soak**: `state/long_cycle_v38_2026-05-28-1745.log`
**Worktree**: `~/chimera-soak-v38-2026-05-28-1745`, branch `chimera-soak/v38-2026-05-28-1745`
**Deliverable commit**: `8a4bf2a [agent] classify items conv-41::qa50..conv-43::qa28 as H2,H4,H2,H2,H2`
**Predecessors**: [v37 postmortem](./v37-soak-postmortem-2026-05-28.md) (CONVERGES, N=5), [v36 postmortem](./v36-soak-postmortem-2026-05-28.md) (CONVERGES, N=1), [v38 charter](./v38-micro-soak-design-2026-05-28.md)

---

## Outcome: CONVERGES

Phase-2 ended `soft_sentinel_deliverable_landed` at iter 8, spend $0.3993. The deliverable [`v38-locomo-temporal-10-item-classification.md`](./v38-locomo-temporal-10-item-classification.md) contains exactly 5 paragraphs with the prescribed `## Item N: <item_id> → <label>` heading pattern for N ∈ {6,7,8,9,10}, ends with `## READY-FOR-REMEDIATION`, and the marker's summary line — `Classified items conv-41::qa50..conv-43::qa28 as H2, H4, H2, H2, H2.` — agrees with the paragraph headings and with the [agent] commit message verbatim. Soak log evidence:

```
[14:21:49] ── phase2 end: soft_sentinel_deliverable_landed  spend=$0.3993 iters=8 ──
8a4bf2a [agent] classify items conv-41::qa50..conv-43::qa28 as H2,H4,H2,H2,H2
```

The substrate scales from N=1 (v36) → N=5 (v37) → **N=10** (v37+v38 cumulative) without operational failure.

## Substantive layer

### 5-item classification (items #6-#10)

| # | item_id | label | one-line summary |
|---|---|---|---|
| 6 | conv-41::qa50 | **H2** | John character-attribution: F2 substituted a flatter persona sketch; arc-compression under top-k=8 truncation |
| 7 | conv-42::qa0 | **H4** | Both F1 and F2 answered "yes" with substantively identical evidence; judging artifact (F2 missed "teammates" keyword) |
| 8 | conv-42::qa14 | **H2** | F2 conflated "Jo" (person) with "Tilly" (stuffed animal); referent-disambiguation collapse under context truncation |
| 9 | conv-42::qa84 | **H2** | F2 inverted temporal polarity (bad → good month) by attributing later events to September 2022 window |
| 10 | conv-43::qa28 | **H2** | F2 named the Harry Potter theme but lost the composer name (John Williams) below attention threshold |

### Substrate-discipline verification

This was the *primary* new test for v38: does the agent honor the skip rule when given a prior deliverable?

- ✅ **Skip rule honored**. The deliverable contains a dedicated `## v37 carry-forward (items #1-#5, NOT re-classified)` section that names v37's commit `b3d14f2`, lists items #1-#5 with their v37 labels (H2,H2,H2,H1,H1), and states "These are not re-examined. This note adds items #6-#10 only." None of v37's item_ids (`conv-26::qa14`, `conv-26::qa22`, `conv-26::qa46`, `conv-26::qa81`, `conv-41::qa45`) appear as classification paragraph headings.
- ✅ **Items #6-#10 match the F1→F2 regressed-set sort**. The preflight Python snippet identified items #6-#10 as `['conv-41::qa50', 'conv-42::qa0', 'conv-42::qa14', 'conv-42::qa84', 'conv-43::qa28']`. The deliverable's paragraph headings name exactly these 5 item_ids in exactly this order.
- ✅ **Heading numbering uses 6-10**, not 1-5 or 1-5+offset.
- ✅ **Independent labels (not pattern-matched from v37)**. The clinching signal: item 7 was labeled **H4** — a hypothesis category v37 never used. v37's distribution was 3× H2 / 2× H1 (no H1 outside the conv-26::qa81 and conv-41::qa45 pair); v38's distribution is 4× H2 / 0× H1 / 1× H4. If the agent had pattern-matched on v37's templates, we would expect either an all-H2 sweep or a similar 3:2 H2:H1 mix; instead, the agent introduced H4 to flag a *judge-stochasticity* failure mode that the locked hypothesis schedule explicitly allowed for (`H4-other: anything not fitting H1/H2/H3`). The item-7 paragraph reasons through the H1/H2/H3 elimination explicitly before settling on H4 — exactly the discipline the schedule asks for.

### Verbatim quotes demonstrating independent reasoning

Item 7 (the H4 case — quoted in full because the H4 selection is the strongest evidence of independent classification):

> F1 answered "yes" with evidence: Nate hangs out with people outside his usual circle at gaming tournaments, makes friends at conventions, plans gaming sessions with new contacts. F2 answered "yes" with substantively identical evidence: Nate hangs out with people outside his usual circle at video game tournaments, hosts gaming parties with multiple attendees. Both answers are affirmative, both cite the same category of evidence (gaming-tournament socializing), and both are factually consistent with the conversation. F2 was graded incorrect despite being substantively correct. This does not fit H1 (the session was clearly retrieved and used), H2 (the evidence is not diluted — both answers draw the same inference), or H3 (no temporal-computation failure). The most parsimonious explanation is H4: soft-judge stochasticity. The expected answer mentions "teammates" specifically, and neither F1 nor F2 uses that word — yet F1 was graded correct and F2 incorrect. This is a judging artifact, not a retrieval or context-budget artifact.

Item 9 (an H2 case that differs structurally from any v37 paragraph — temporal-polarity inversion rather than pure attribute substitution):

> F2 reversed the temporal polarity (bad month → good month) by attributing events from a later time period to the September 2022 window. … H2 is the best explanation: under top-k=8 truncation, the temporal anchors (September 2022 dates, the sequence of tournament-failure-then-later-win, the laptop-crash-then-later-script-success) got blurred across the compressed context window, and the answerer collapsed distinct events from different time periods into the query's timeframe, inverting the polarity.

### Cumulative distribution across v37+v38 (10 of 19 items)

| label | v37 (items #1-5) | v38 (items #6-10) | cumulative |
|---|---|---|---|
| H1 (retrieval-distractor) | 2 | 0 | 2 |
| H2 (context-budget dilution) | 3 | 4 | 7 |
| H3 (category-fundamentals) | 0 | 0 | 0 |
| H4 (other / judging artifact) | 0 | 1 | 1 |

H2 dominates (7/10); H3 has yet to appear in 10 classifications, which is itself a finding — temporal-reasoning regressions in the LoCoMo F1→F2 set appear to be predominantly context-budget rather than category-fundamentals failures. Worth recording in the noise-envelope context for ADR 0142.

## Operational layer (per-guard verdicts)

| guard | verdict | evidence |
|---|---|---|
| ADR 0141 detector (worktree-branch-drift) | ✅ ok | `chimera doctor` in preflight reported "secondary worktree" classification on the sanity worktree |
| SQLite thread-affinity fix (PRs #105/#107) | ✅ ok | no thread-affinity errors in 36-min soak; soak's own `chimera run` invocations all completed |
| Scope-check design-note matching (PR #119) | ✅ ok — **v38 design note matched** | preflight: `find_active_design_note` on `chimera-soak/v38-preflight` returned `v38-micro-soak-design-2026-05-28.md` (not v34/v36/v37) |
| Forward-progress watchdog (PR #109) | ✅ silent (not needed) | soak made monotone progress every iter (iter 1→8, spend $0→$0.40); watchdog never fired |
| Task-completion watchdog (PR #113) | ✅ silent (not needed) | soft-sentinel fired first |
| ACT-budget enforcement (PR #115 / today's wiring) | ✅ silent (not needed) | no iter approached 240s budget; longest gap iter 5→6 was ~6 min wall but that includes idle scheduling, not single-ACT-phase time |
| Phase-1 sentinel (PR #118) | ⚠️ noted — see below | phase-1 ended `ready_marker_found` at iter 1, spend $0.000 |
| wiring_coordinator | ✅ silent (as expected) | per PR #111 honesty fix, no wiring_coordinator references in this run |

### Phase-1 sentinel note

Phase-1's sentinel target was set by the runner to `mind/research/v37-locomo-temporal-5-item-classification.md` — the *prior* deliverable now present on main after PR #123. The sentinel matched on iter 1 with $0 spend, advancing immediately to phase-2. This is operationally correct (phase-1 is "engines off — validate priors are in place") but the runner's sentinel-target wiring is worth flagging as a follow-up: a future fan-out chip should distinguish "predecessor present" (validate input) from "deliverable landed" (validate output) more explicitly to avoid confusion in postmortems. Not a defect for v38 — phase-2 did all the real work and converged cleanly. Filing as a runner-template housekeeping note rather than fixing inline.

## Cost amortization — v37 vs v38

| metric | v37 (N=5) | v38 (N=5 new, fan-in from v37) | delta |
|---|---|---|---|
| Wall time | ~10 min | ~36 min | 3.6× |
| Phase-1 iters / spend | 2 / $0.117 | 1 / $0.000 | (P1 effectively free for v38 because predecessor satisfied marker on iter 1) |
| Phase-2 iters / spend | 1 / $0.019 | 8 / $0.399 | 8× iters, 21× phase-2 spend |
| Total spend | $0.136 | $0.399 | 2.9× |
| Per-item (this soak's 5 items) | $0.027 | **$0.080** | **2.9× degradation** |
| Per-item amortized over cumulative 10 items | n/a | $0.054 (treating v37's $0.136 + v38's $0.399 across 10 items) | — |

### Honest framing of the per-item cost

The charter pre-registered amortization bands: `≤$0.05/item` → v39 at N=19; `$0.05–$0.10` → v39 at N≈10 (items #11-19, 9 items); `>$0.10` → smaller. v38's per-item rate of **$0.080** falls in the middle band.

The honest framing is that **v37's $0.028/item was a lower bound, not a sustainable rate**. v37 shipped 5 paragraphs in a single phase-2 iter ($0.019) because the agent had no prior context to integrate; the cost was dominated by phase-1's $0.117 of reading-and-thinking. v38 had to (a) read v37's deliverable, (b) plan the skip rule, (c) derive items #6-#10 from the regressed-set sort, (d) reason through 5 new items including one off-pattern H4 case, all in phase-2 — and took 8 iters to do it. v38's per-iter spend (~$0.05) is steady; what grew is the number of iters the substrate needed to integrate context.

This is a real signal: **the substrate's marginal cost is iter-count-dominated, not API-spend-dominated**, and iter count grows with how much prior context the agent must integrate. Extrapolating: v39 at N=9 (items #11-19) would need to integrate both v37 and v38, which is more prior context than v38 had — expect per-item to drift further toward $0.10. v39 at N=19 (rewrite all in one note) would likely cost less per item than v39 at N=9 because rewriting from scratch is cheaper than reading-and-integrating, but it discards v37+v38's specific paragraphs and is harder to audit.

### ACT-phase duration signal

The charter flagged v37's ACT-phase duration (88.65s) as a baseline. v38's per-iter wall time averaged ~4.5 min, but the soak log does not break out ACT-phase time per iter directly (the runner reports phase-2 iter boundaries, not ACT-phase boundaries within a single iter). I am not asserting an ACT-duration delta without that decomposition. Operator may want to instrument ACT-phase wall time as a runner-template improvement.

## Recommended next chip

Per the charter's pre-registered decision rules and v38's per-item rate ($0.080, middle band):

> **Charter v39 at N=9** (items #11-#19 of the regressed-set sort), with a hard cap of $1.50 (≈$0.166/item ceiling — generous given v38's $0.080 baseline). Predecessors for v39's skip rule: v37's `v37-locomo-temporal-5-item-classification.md` + v38's `v38-locomo-temporal-10-item-classification.md`. Substrate-discipline check for v39: confirm the agent skips both v37's items #1-#5 *and* v38's items #6-#10, and that v39's paragraphs use heading numbering 11-19.

**Do NOT charter v39 from inside this chip.** This is the operator's call.

Secondary recommendations (out-of-scope, file as follow-up chips):
- **Soak runner template cleanup**: phase-1 sentinel-target wiring is ambiguous between "predecessor present" and "deliverable landed". Add a config knob so postmortems can read intent off the runner banner.
- **ACT-phase timing instrumentation**: emit ACT-phase wall time per iter so cost-amortization tables can include the v37-baseline comparison the charter asked for.
- **ADR 0142 noise-envelope update**: with 7/10 of the regressed temporal-reasoning items classified as H2 (context-budget dilution), the noise-envelope amendment should note that temporal-reasoning regressions are dominated by context-budget rather than category-fundamentals failures.

## Honest disclosures

- ACT-phase wall time per iter is **not measured** from the soak log; the "per-iter wall time ~4.5 min" figure is an arithmetic average and includes scheduler/IO time, not just ACT phase. Charter asked for a v37 (88.65s) vs v38 ACT-phase comparison; I cannot deliver that without runner instrumentation. Flagged above.
- v38 phase-1 effectively cost $0 because the soak's phase-1 sentinel target was pre-satisfied by v37's deliverable existing on main (post-PR-#123). That is operationally correct but means v38's $0.399 is *not* directly comparable to v37's $0.136 as "same-shape soaks" — v38 saved phase-1 spend that v37 paid. Adjusted comparison: phase-2-only spend was v37 $0.019 vs v38 $0.399, which is a 21× growth, not 2.9×. The honest read is that phase-2 carried all of v38's reasoning load.
- One **runner-template inconsistency** noted (sentinel-target semantics) but not fixed inline per discipline; filed as a follow-up recommendation rather than amending the runner script in this chip.
- H4 introduction is treated as a positive signal of independent reasoning, but a skeptical reading is also possible: "the agent invented a new category to label a hard case." I judge the agent's reasoning in the item-7 paragraph (explicit H1/H2/H3 elimination, citing the specific keyword `teammates` that the judge cared about) sufficient to credit it as evidence-led, but operator may disagree.
- No comparison data on whether **judge stochasticity** (item 7's H4) actually accounts for some of the other ostensibly-H2 cases. Worth a separate "rerun item 7 under multiple judge seeds" sub-investigation if operator wants to nail that down.

## PR plan

- Branch: `chore/v38-soak-postmortem`
- Title: `docs: v38 fan-out soak postmortem — CONVERGES`
- Body: this note (1 file)
- Operator-gated merge per standing rule.
