# v36 Micro-Soak Postmortem — 2026-05-28

**Soak**: `chimera-soak/v36-2026-05-28-1537`
**Runner**: `scripts/long_cycle_soak_v36.sh` (shipped in [PR #115](https://github.com/elementalcollision/chimera/pull/115), main `946d59a`)
**Wall time**: 11:37:39 → 11:56:50 PDT (~19 minutes)
**Total spend**: ~$0.24 (phase 1 $0.2203, phase 2 $0.0174) — well under the $5+$5 cap
**Charter**: classify ONE LoCoMo F2 temporal-reasoning regression item; commit ONE-file research note
**Substrate**: post-v4.116.0 hardening cascade (PRs #103, #105, #108, #109, #110, #111, #113)

## Outcome: **CONVERGES**

One commit landed on the soak branch:

```
9cfb644 [agent] classify conv-26::qa14 as H2
```

Diff scope: exactly one file (`mind/research/v36-locomo-temporal-one-item-classification.md`), as the charter required. Soft-sentinel fired post-iter-1 of phase 2 with `soft_sentinel_deliverable_landed`. No scope-check refusal. No watchdog fired after the planned phase-1 → phase-2 handoff. No wiring_coordinator auto-PR.

This is the **first time** the autonomous-loop substrate has converged end-to-end on a substantive deliverable since the v35 cascade began. Five v35 attempts could not complete the multi-item temporal-regression analysis; v36's atomic single-item scope is the load-bearing test of PR #112's structural hypothesis ("no per-step checkpointing within ACT"). The hypothesis is **operationally validated**: when the unit of work fits inside the ACT-budget window, the loop converges.

## Substantive layer

**Selected item**: `conv-26::qa14` (first by `item_id` sort order — agent correctly applied the no-discretion selection rule).

**Hypothesis label**: **H2 (context-budget dilution)**.

**Classification paragraph (verbatim from commit 9cfb644)**:

> F1 answered correctly with a concrete "likely no" by grounding in Caroline's expressed gratitude for the support she received and concluding that without it, her motivation would not have developed the same way. F2 answered with hedging ("does not provide a direct answer... uncertain"), despite the fact that the same conversation material was available. Since F1 (no retrieval, full session) used the same answerer model (`gpt-4o-mini`) and gave a confident, correct answer, the F2 failure is not a retrieval-distractor problem (H1) — the relevant session was almost certainly selected, as the question is clearly about Caroline and the conversation is about Caroline. Nor is it a category-fundamentals problem (H3) because F1 _did_ succeed at this exact temporal counterfactual without the full session sequence; the answerer can do this kind of reasoning with the right context. The most plausible explanation is H2: when top-k=8 truncated the answerer's context, the temporal-anchoring signal (Caroline's gratitude for past support → motivation linkage) was diluted by the other sessions, causing the answerer to retreat to epistemic hedging rather than committing to the counterfactual inference that F1 successfully made.

**Diagnosis defensibility** — sanity-checked:
- F1 hypothesis text quoted in the note **does** appear in `/tmp/locomo-f1/hypotheses.graded.jsonl` for the same `item_id` (Caroline / counseling / gratitude-for-support framing — verified by inspection of the deliverable's "Item details" block which quotes the JSONL fields directly).
- F2 hypothesis text ("does not provide a direct answer... uncertain") matches the hedging pattern characteristic of `context-budget dilution` under retrieval truncation.
- The H2 label is consistent with the elimination argument (H1 ruled out by same-conversation-clearly-selected, H3 ruled out by F1 success with same answerer).
- The note avoids citing percentages or aggregate statistics — no obvious confabulation.

The diagnosis is **defensible**. Whether H2 is the *correct* label is a separate question that would require a counterfactual experiment (e.g. rerun this item with `--retrieval-top-k 16` or `--retrieval-top-k 32` and observe whether the hedging dissolves); v36's atomic scope intentionally does not chase that question.

## Operational layer (per-guard verdicts)

| Guard | PR | Verdict | Evidence |
|---|---|---|---|
| ADR 0141 detector | [#103](https://github.com/elementalcollision/chimera/pull/103) | **PASS** | Preflight `chimera doctor` correctly flagged the throwaway worktree as a secondary worktree; soak ran from secondary worktree without thread-affinity failures (which were the v35-postmortem chip-1 blocker before [#105](https://github.com/elementalcollision/chimera/pull/105)). |
| SQLite thread-affinity fix | [#105](https://github.com/elementalcollision/chimera/pull/105) | **PASS** | Zero SQLite-related tracebacks across the run; `chimera run` invocations from the secondary worktree completed without the `objects created in a thread can only be used in that same thread` failure pattern. |
| Pre-commit scope check | [#108](https://github.com/elementalcollision/chimera/pull/108) (ADR 0146) | **PASS with anomaly** | Fired exactly once (1 entry in `state/scope_check_events.jsonl`), verdict `allow`, `offending_paths: []`. The agent's commit was correctly permitted. **Anomaly**: the matched design note was `v34-preference-dialectic-design.md`, not the v36 design note, and the recommendation's `allowed_paths` (`dialectic.py`, ADR 0137, etc.) had no overlap with the staged path. The commit was allowed because research notes under `mind/research/*` are auto-allowed by the v4 journal-auto-allow rule independent of the recommendation. The guard's *outcome* was correct (allow the research-note commit), but the *reasoning trace* matched the wrong design note. See "Follow-ups" below. |
| Forward-progress watchdog | [#109](https://github.com/elementalcollision/chimera/pull/109) | **N/A** | Did not fire. The task-completion watchdog (additive, [#113](https://github.com/elementalcollision/chimera/pull/113)) caught the degenerate state first. |
| ACT-budget enforcement | [#110](https://github.com/elementalcollision/chimera/pull/110) | **PASS — 3 cancellations** | Cancelled phase-1 iters 1, 2, 3 at the 240s budget. Iter 1: 0/5 tasks completed (tasks hit `max_rounds=12` before phase budget). Iter 2: 2/5 completed (the two early tasks — find items, pick first). Iter 3: 0/3 completed (continuing the inspection task). The cancellations did **not** prevent forward progress: iter 4 ran under budget (act=76s) and completed all three remaining tasks. This is the cancel-and-replan pattern working exactly as designed in the v35-postmortem ladder #6 charter. |
| wiring_coordinator | [#111](https://github.com/elementalcollision/chimera/pull/111) | **PASS** | Zero invocations in the soak log. The branch was left in the worktree for manual operator review per the stripped-prose update; no auto-PR, no auto-merge. |
| Task-completion watchdog | [#113](https://github.com/elementalcollision/chimera/pull/113) | **FIRED at phase-1 iter 8** | `FATAL: no task completion (6 iterations with completed=0/M tasks at budget cap)`. This is the **load-bearing guard** for v36 — without it, phase 1 would have been stuck in the post-deliverable inbox-empty state (cycle/spend frozen at 149/$0.2203 from iter 5 onward) until the forward-progress watchdog eventually caught it 5+ iters later. Phase 1 exit reason `no_task_completion last_k=0 spend=$0.2203 iters=9`. Phase 2 picked up immediately and committed the deliverable in 1 iter. |

## A finding about the runner

A bug in `scripts/long_cycle_soak_v36.sh` would have produced a STALLS-or-worse outcome without PR #113:

Phase 1's `ready_marker_found` exit condition checks for `## READY-FOR-REMEDIATION` in `INVESTIGATION_DOC` — but `INVESTIGATION_DOC` is set to the *input reference doc* (the F2 retrieval ablation note), not the *output deliverable* the agent writes (`v36-locomo-temporal-one-item-classification.md`). The soft-sentinel (which IS targeted at the deliverable) is only armed during phase 2. So phase 1 has no path to exit on "deliverable landed" — it must time out via budget, wall-clock, or a watchdog.

PR #113's task-completion watchdog turns out to be precisely the mechanism that catches this case: once the agent has written the deliverable, the inbox tasks are all completed and subsequent iters show `tasks_seen=0 completed=0/0` (with `completed=0` per the soft-sentinel-style measurement), so the watchdog trips at 6 iters of zero-task-completion and forces the phase-1 → phase-2 transition. **Without PR #113**, phase 1 would have run for ~200 stuck iters or until forward-progress watchdog fired ~5 iters later — either acceptable in this small-deliverable case but pathological at larger scope.

This is **not a v36 bug we should fix in this PR** (scope: postmortem only). It is a finding to charter as a follow-up runner-correctness chip (see Follow-ups below).

## Comparison to v35 attempts

| Attempt | Wall time | What blocked it | Deliverable landed? | Commit landed? |
|---|---|---|---|---|
| v35 #1 | minutes | SQLite thread-affinity from secondary worktree | No | No |
| v35 #2 | minutes | Same (pre-PR #105) | No | No |
| v35 #3 | minutes | Same | No | No |
| v35 #4 | hours | Forward-progress watchdog blind-spot: cycle/spend advancing while tasks never completing | Partial (design notes only) | No (operator-terminated; "operationally PASS, substantively FAIL") |
| **v36** | **~19 min** | **Nothing — converged via PR #113 task-completion watchdog** | **Yes** | **Yes** |

v36's outcome **strengthens** PR #112's structural hypothesis: the autonomous loop *can* deliver a substantively defensible artifact when the atomic unit is sized to fit inside the ACT-budget window, and the post-v4.116.0 guard stack handles the degenerate inbox-empty state correctly. The hypothesis is not falsified.

It is worth being precise about what was tested. v36 tested **one item, classification only, no code change**. v36 did **not** test:
- Multi-item iteration within one soak
- Code modification deliverables (R2+ recommendations)
- Cross-session continuity (the soak is short enough to fit one Claude session)
- The forward-progress watchdog as the primary watchdog (PR #113 caught the case first)

A v37 charter that fans out to N items is the natural next step but is the operator's call, not this chip's.

## Honest disclosures

Following the standard set by the v35 postmortems:

1. **My STALLS prediction was wrong mid-soak.** When I observed phase-1 iters 5, 6, 7 with frozen cycle and spend, I predicted the outcome would be STALLS via forward-progress watchdog and posted that to the operator. The task-completion watchdog ([#113](https://github.com/elementalcollision/chimera/pull/113)) fired first at iter 8 — by design, since it's tuned tighter than forward-progress for exactly this case. The actual outcome was CONVERGES via planned phase-1 → phase-2 handoff. I should have re-read the runner more carefully before predicting; the answer was in the source code.

2. **I initially misread the launch-banner "phase-1 sentinel target" line** as flagging a runner defect (the launch log shows `phase-1 sentinel target: .../locomo-f2-retrieval-ablation-2026-05-27.md`, the F2 reference doc, not the v36 deliverable). On closer reading the `INVESTIGATION_DOC` variable IS the input reference doc and the label is honest. The actual runner defect (phase-1 exit logic checks the wrong file) is a different and more subtle issue, documented above.

3. **Scope-check anomaly.** The pre-commit scope check matched the wrong design note (v34 dialectic) for a v36 commit. The verdict was correct (allow) only because of the `mind/research/*` journal-auto-allow rule, not because the scope-check reasoning was sound. If the deliverable had been a code change (R2+), the wrong-design-note match could have allowed or refused for the wrong reason. Charter follow-up.

4. **The classification's "correctness" is not established.** This postmortem says the diagnosis is *defensible* (evidence-grounded, no confabulation, logically consistent). It does not say H2 is the *right* label. A retrieval-top-k sweep on the single item would be the cheap experiment.

5. **N=1.** v36 converged on one item, in one soak attempt. One success after five failures is not a stable result. Charter v37 to test n>1 and accumulate confidence.

## Follow-ups (chip charters — not opened by this chip)

The operator decides whether to charter any of these:

1. **Runner-correctness chip**: fix phase-1's `ready_marker_found` to check the deliverable file (`SOFT_SENTINEL_ALLOWED_FILES` set during phase 1 with the same `true` test gate, or a dedicated phase-1 sentinel path variable). Today PR #113 masks this defect; a future soak with different timing could re-surface it.
2. **Scope-check design-note matching chip**: investigate why the v34 dialectic design note matched a v36 commit — likely a substring-or-recency heuristic problem. PR #108 verdict was right by accident here.
3. **v37 charter** (the natural successor): fan out to N items per soak, with N to be chosen by the operator based on per-soak budget tolerance. ADR-worthy: this is the first chip that should run multiple items autonomously.

## File + PR

This postmortem is the only file in `chore/v36-soak-postmortem`. Operator-gated.
