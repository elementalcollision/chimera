# Adopt Proposal — Proposer-Quality Scoring

*Drafted 2026-07-20 · from the Capability Matrix at `mind/research/capability-matrix.html`*

## 1. Operationalised Claim

**Proposer-Quality Scoring is the single most under-implemented capability across the 8 surveyed agent frameworks.** It has **zero first-class implementations** and **one partial** across the field.

- **Chimera (partial)** — ADR 0090 (`proposer-acceptance-scoring`) tracks per-mutation-type acceptance rates over a rolling window and auto-degrades proposers below threshold. This is an *output-side* metric — it judges after the operator acts — and has no *real-time input-side* quality signal (no confidence estimates at proposal time, no per-proposal quality prediction). [fn96 in matrix]
- **Every other framework: absent.** LangGraph → no built-in proposal-quality scoring; relies on offline LangSmith eval runners (fn5). CrewAI → absent (fn18). AutoGen → absent (fn31). OpenAI Agents SDK → absent (fn44). OpenClaw → absent (fn57). Google ADK → absent (fn70). Mastra → absent (fn83).

Seven frameworks have no proposer-quality signal whatsoever. Chimera has the only foothold — a retrospective acceptance-rate gate — but lacks the input-side quality scoring that would let an operator allocate attention before proposals pile up.

Note: **Drift/Anchor Primitives** is equally absent (zero first-class, Chimera-only partial via ADR 0089 signal-density gates). But drift is downstream of proposer quality — a system that can't score its own proposals has no anchor to drift *from*. Proposer-quality scoring is the prior gap.

## 2. Scoring

| Axis | Score | Justification |
|---|---|---|
| **Operator value** | **4 / 5** | The operator's scarcest resource is attention. A proposer-quality score turns an undifferentiated firehose of `skill_proposal`, `task_split`, `config_change` into a triaged feed. It also feeds directly into trust gating (ADR 0048), mutation-queue operator gates (ADR 0041), and adaptive budgets (ADR 0028). One point off from 5 because the acceptance-rate gate (ADR 0090) already provides the coarse "this proposer is broken" signal; the remaining gap is per-proposal confidence. |
| **Implementation cost** | **2 / 5** | Chimera already has: (a) the `proposer_status` table (ADR 0090), (b) per-proposal `mutations` rows with terminal-state tracking, (c) the `proposer_scoring` module with `compute_score` / `evaluate_and_update`, (d) chronicle entries with structured metadata. The missing piece is a lightweight prediction layer — e.g. a score column on `mutations` populated at `create_mutation` time from cheap heuristics (novelty of proposed change vs chronicle history, proposer's current acceptance rate, complexity of diff). No new infrastructure; ~150 lines of Python plus tests. |
| **Alignment risk** | **3 / 5** | A proposal-quality scorer is itself a proposer of sorts — it encodes an opinion about what "good" proposals look like. The risk is that the scorer trains the operator to ignore proposals it rates low, and the operator misses a correct-but-novel proposal the scorer couldn't recognise. Mitigated by: scorer output is advisory only (never blocks `create_mutation`), operator sees the raw proposal alongside the score, and the acceptance-rate feedback loop (ADR 0090) provides a ground-truth check on whether the scorer's confidence correlates with operator decisions. Not a 2 because heuristic scores have a way of hardening into gates over time. |

## 3. Implementation Sketch

### ADR slot

**ADR 0092** — next free after 0091 (`selective-engine-enable`).

### Files touched

| File | Nature of change |
|---|---|
| `chimera/core/proposer_scoring.py` | Add `predict_quality(proposer, payload) -> float` — heuristic scoring function that returns 0.0–1.0 confidence. Factors: proposer's rolling acceptance rate (weight 0.4), novelty of proposed change vs last N chronicle entries (weight 0.3, via FTS5 similarity), complexity of diff (weight 0.3, penalise giant config rewrites). |
| `chimera/core/adaptation.py` | At `create_mutation` time, call `predict_quality` and store result in `mutations.quality_score`. |
| `chimera/core/task_split_proposal.py` | Same hook as adaptation.py. |
| `chimera/memory/audit.py` | Same hook for config-change proposals. |
| `chimera/db/migrations/` | Add `quality_score REAL` column to `mutations` (nullable, default NULL for pre-existing rows). |
| CLI / `chimera/cli/proposers.py` | Extend `chimera proposers list` to show mean quality score per proposer type. |
| `tests/test_proposer_scoring.py` | Add ~12 tests: `predict_quality` returns float in [0,1], low acceptance rate → low quality, novel change → moderate quality, giant diff → penalised, empty payload → ~0.5, `create_mutation` populates column, migration backfill leaves NULL, CLI output includes quality column. |

### Test surface

- **Unit**: `predict_quality` with known inputs (12 cases).
- **Integration**: end-to-end `create_mutation` → `quality_score` populated → visible in `chimera proposers list`.
- **Regression**: existing `test_proposer_scoring.py` (19 tests from ADR 0090) must pass unchanged; the new column is additive and nullable so no migration breakage.
- **Edge cases**: empty chronicle (no history → novelty defaults to 0.5), single-proposal proposer (not enough data for acceptance rate → defaults to 0.5), very long diff (>10K chars → capped at penalty floor of 0.2).

### Expected mutation types

After deploy, the observation engines will emit proposals with visible quality scores. The operator should expect:

1. **`skill_proposal` quality drifts downward** as the namespace saturates (novelty factor drops).
2. **`task_split` quality correlates loosely with task complexity** — simple splits score higher.
3. **`config_change` quality is bimodal** — small tuning changes score high, giant rewrites score low.
4. **Chronicle-driven feedback**: if the operator consistently rejects proposals with quality > 0.7, the heuristic weights need tuning (the scorer is overconfident). If the operator consistently accepts proposals with quality < 0.3, the scorer is under-confident. ADR 0090's acceptance-rate gate provides the ground-truth signal.

### Non-goals

- **No ML model.** The heuristic is deliberately simple — weighted sum of three factors. A learned model (even logistic regression over proposal features) introduces a training-data dependency and a model-drift surface that isn't warranted for a first cut.
- **No blocking on low quality.** The score is advisory. `check_can_propose` (ADR 0090) gates only on acceptance-rate degradation, not on per-proposal quality.
- **No cross-proposer calibration.** Each proposer type is scored independently; no attempt to make a `skill_proposal` score of 0.8 "mean the same thing" as a `config_change` score of 0.8.
- **No dashboard widget in this ADR.** The JSON output of `chimera proposers list --json` gains a `quality_mean` field; dashboard consumption is a follow-up.

## Why This Is the Right Gap to Close

The capability matrix reveals a field-wide blind spot: nobody scores proposal quality. LangGraph has an operator gate but no score. CrewAI/AutoGen/ADK/Mastra have neither. Chimera has the operator gate *and* the acceptance-rate feedback loop — the only framework with both halves of the feedback circuit. Adding per-proposal quality scoring closes the loop entirely: propose → score → operator decides → acceptance tracked → score recalibrated. That's a capability no other framework has even sketched, and it sits at the intersection of the Trust & Quality and Cost & Operations columns — exactly where operator leverage is highest.


## Cross-witness critique

**(i) Under-implemented claim:** The "single most under-implemented" framing is selection-biased, not empirical. The proposal surveyed 8 frameworks across a self-selected capability taxonomy (`capability-matrix.html`) — there's no evidence that proposer-quality scoring is a *worse* gap than, say, cross-sub-agent conflict detection, fine-grained cost attribution, or inter-framework migration tooling, none of which appear in the matrix. The Drift/Anchor hand-wave ("drift is downstream of proposer quality") is reversible: you could just as easily argue proposer-quality is downstream of having stable anchors to evaluate proposals *against*. The "zero first-class" claim is tautological — the proposal defines "first-class" to exclude LangSmith's offline eval runners, which *are* proposer-quality scoring, just not inline. A less motivated reading would score LangGraph as "partial" and Chimera's acceptance-rate gate as "partial," making the gap 0 first-class and 2 partial — less dramatic.

**(ii) Scoring honesty:** The 2/5 implementation-cost score strains credibility. Eight files touched, a new DB migration, a new CLI subcommand, and 12+ tests aren't "~150 lines of Python plus tests" — the test boilerplate alone (12 cases × setup/assert blocks) approaches 150 lines, and the FTS5 novelty integration (query construction, result parsing, threshold tuning) is a hidden complexity sink. A fairer score is 3/5. The 3/5 alignment-risk score is more honest in the body than the number suggests: the proposal explicitly warns that "heuristic scores have a way of hardening into gates over time" but offers no concrete anti-hardening mechanism beyond "it's advisory." Without an expiry or recalibration trigger on the heuristic weights themselves, the 3/5 is aspirational — the realised risk is closer to 4/5 once operators internalise the scores.

**(iii) Most likely failure mode:** **The cold-start flatline.** New proposer types (or any proposer after a chronicle rotation) get `0.4×0.5 + 0.3×0.5 + 0.3×0.5 = 0.5` — an uninformative midpoint that masks genuine quality differences. This isn't an edge case; it's the *default* for any proposer introduced after deploy, and the proposal's only answer is "defaults to 0.5." The system will spend its first weeks indistinguishable from random, precisely when operator attention is most needed to calibrate trust in new proposer types. The FTS5 novelty check compounds this: FTS5 does lexical overlap, not semantic similarity, so a proposal that rephrases an existing idea scores as "novel" while a genuinely novel idea using familiar vocabulary scores as "redundant." And the chronicle-driven feedback loop (bullet 4 in Expected Mutation Types) is described but not implemented — there's no ADR section for *how* the weights get retuned, just a hope that the operator will notice and manually adjust.

**(iv) Stronger alternative gap:** **Proposer-conflict detection.** Chimera currently has no mechanism to detect when a `task_split` proposal and a `config_change` proposal interact — e.g., a task-split that moves work onto a path a pending config-change is about to deprecate. This is operator value 5/5 (prevents silent breakage that wastes operator time), implementation cost 2/5 (cross-reference `mutations` table by affected paths/keys, flag overlaps), alignment risk 2/5 (purely mechanical — no opinion encoded about proposal "goodness," just flagging interactions). It beats proposer-quality scoring because the failure mode of missing a conflict is strictly worse than the failure mode of missing a low-quality proposal (the former breaks the system; the latter wastes attention). And unlike quality scoring, conflict detection has no cold-start problem: the first proposal pair that conflicts is immediately detectable.

**(v) What data would change my mind:** Over a 30-day observation window, I'd want to see: (a) **acceptance-rate variance** across proposer types — if the range is tight (all within ±0.1 of mean), per-proposal scoring adds no triage value because the operator already treats all proposers similarly; (b) **operator decision latency** per proposal — if the operator spends <5 seconds on 90% of proposals, a quality score saves negligible attention, whereas if 20% of proposals consume >60 seconds each, triage would help; (c) **chronicle FTS5 query cost** — measure the actual wall-clock time of FTS5 similarity queries against a growing chronicle; if median latency exceeds 50ms per query, the scoring function adds observable lag to every `create_mutation` call. If (a) shows high variance, (b) shows attention bottlenecks, and (c) stays fast, the proposal is right. If any of these fails, the gap is elsewhere.
