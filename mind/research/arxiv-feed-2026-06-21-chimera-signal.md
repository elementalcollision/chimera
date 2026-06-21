# arXiv work-item feed — Chimera signal triage (2026-06-21)

Source: `Agent_Data/.../arxiv_feed` (weekly scrape, Mon ~07:00). This is an
**intelligence source, not an auto-task source** — a paper is not a scoped PR.
Chimera consumes it by triaging to signal, capturing adoption ideas here, and
(operator-gated) turning a few into hand-authored backlog specs / ADR work.

## This run

- Window 7d → 309 records (leibniz 123 / newton 73 / **chimera 113**).
- **~12 of 113 on-mission; ~85% noise.** Dominant noise: generic cs.CV /
  vision-language (egocentric video, SAR, optical flow, VLA manipulation, …),
  then classic cs.LG theory. Cause: the deliberately-broad `benchmark` (91 hits)
  and `algorithm` (28) keywords + cs.CV cross-lists. → motivates the scraper tune.

## On-mission picks (ranked)

1. **Phoenix — Safe GitHub Issue Resolution via Multi-Agent LLMs** (arXiv:2606.20243, cs.SE).
   Chimera's mission as a paper: 6-agent issue→PR pipeline, label-based webhook
   state machine, **7 layered safety controls**, and a **baseline-aware test gate**
   (require no pass-to-pass regressions before the PR). 75% oracle-resolve on
   SWE-bench Lite, zero regressions; documents real deploy failure modes.
   → **ADOPT: baseline-aware regression gate** (see Adoption backlog #1).
2. **Connect-the-Dots / CoD** (arXiv:2606.20002, cs.LG) — RL framework
   ([Trinity-RFT](https://github.com/agentscope-ai/Trinity-RFT)) training a
   long-lifecycle agent to self-improve via interleaved solve/update-context
   episodes; OOD + "Ralph-loop" generalization. → evaluate repo for self-improvement.
3. **ENPIRE — Agentic Self-Improvement** (arXiv:2606.19980, cs.AI) —
   reset→execute→verify→**evolve** harness with a self-editing Evolution module +
   parallel fleet rollout. Cleanest blueprint for our soak + self-improvement loop.
4. **Efficient & Sound Probabilistic Verification for AI Agents** (arXiv:2606.20510,
   cs.CR) — Datalog runtime policies with **sound violation-probability bounds**
   when the detectors themselves are fallible. → rigour for our trust/safety gates.
5. **NRT-Bench — multi-turn agent red-teaming** (arXiv:2606.20408, cs.CR) — the
   same guardrail stack that lowers one model's attack success **raises** another's;
   frontier vulns are near-disjoint. → **validate guardrails per-model** across our
   multi-LLM roster, never assume portability.
6. **Defensive Misdirection vs automated attacks** (arXiv:2606.20470, cs.CR) —
   predictable refusals leak a gradient; detect-and-misdirect bounds asymptotic ASR.
   → don't emit predictable refusal text from guardrails.
7. **The Correctness Illusion in LLM GPU Kernels** (arXiv:2606.20128, cs.SE) —
   fixed-input `allclose` certifies buggy code; **seeded property/fuzz vs a
   high-precision reference** catches it. → strengthen "is my generated code correct?".
8. **Hierarchical Recovery for multi-agent systems / H-RePlan** (arXiv:2606.20487,
   cs.CL) — separate local strategy-recovery from global replanning via a failure
   abstraction. → scope-aware failure taxonomy in the orchestrator (local retry
   before expensive replan).

Secondary / track: Multi-LCB (multi-language code-gen bench, 2606.20517),
SolidityBench (repo-level gen; RAG>ICL, >2 in-context examples hurt, 2606.19988),
SKILL.md trajectory-mining (honest negative: readability ≠ transfer, 2606.20363).

## Adoption backlog (concrete, ranked)

1. **Baseline-aware regression gate (from Phoenix).** Our foreign-PR gate (B.4e/
   MF-2) runs only the *scoped* verify_cmd (new test red-on-base→green-at-HEAD). A
   foreign task that EDITS source could break an existing passing test undetected.
   Add a no-pass-to-pass-regression check (broader suite at base vs HEAD; fail on
   pass→fail). Forward-looking — current tasks are additive tests. → ADR 0186 rung.
2. **Per-model guardrail validation (from NRT-Bench).** Our safety gates are applied
   uniformly across the LLM roster; validate each guardrail per-model.
3. **Seeded-fuzz correctness oracle (from the kernels paper).** For tasks where the
   gate is a single test, add property/fuzz + reference-oracle where feasible.
4. **Sound probabilistic gate bounds (from 2606.20510).** When a gate detector is an
   LLM/classifier, bound its violation probability rather than trusting a pass/fail.

## Meta

- Recurring ingestion (planned): the weekly chimera feed → LLM triage → a digest
  like this in `mind/research/`, operator reviews → adoption backlog → specs/ADRs.
- Scraper tune (planned): cut the ~85% chimera-feed noise at source.
