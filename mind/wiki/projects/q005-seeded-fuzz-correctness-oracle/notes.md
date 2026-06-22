# Notes — q005

*Topic:* Seeded-fuzz correctness oracle — is it feasible as a Chimera code-production gate, and which oracle source fits the code Chimera actually writes?

*Date:* 2026-06-22

## Findings

## Findings Note: Fuzzing Is Easy; The Oracle Is the Whole Problem — Match It to What You Build

The motivating paper is *The Correctness Illusion in LLM GPU Kernels* ([arxiv.org/abs/2606.20128](https://arxiv.org/abs/2606.20128)): a fixed-input `allclose(out, expected)` test routinely **certifies buggy code**, because it checks exactly one point in the input space. A kernel can match the reference on the one tested shape and be wrong on every other. The fix the authors use is **seeded property/fuzz testing against a high-precision reference** — many randomized inputs, each checked against an independent oracle.

This maps onto a real Chimera weakness. A CRAWL/backlog task's acceptance gate is a single command (`spec.test` self-repo, `verify_cmd` foreign) — usually a handful of fixed assertions. That is the same correctness illusion: the gate proves the code works *on the examples the agent thought to write*, not in general.

**But the technique does not transfer for free — the crux is the oracle-source problem.** Generating fuzzed inputs is trivial; the hard part is *what you compare the output against*. There are only three real sources, and they differ wildly in cost and applicability:

1. **Differential — the pre-change code is the reference.** For behavior-preserving work (refactor, optimize, migrate), the old implementation is a free, high-precision oracle: fuzz inputs through old-vs-new and assert equality. Clean, zero spec burden — but *only valid when behavior is supposed to be preserved*. A bug-fix or feature is supposed to change behavior, so old≠new is correct there; the differential oracle would raise false alarms.
2. **Property / metamorphic — an invariant is the oracle.** Range bounds, round-trips (`decode(encode(x)) == x`), idempotence (`f(f(x)) == f(x)`), ordering, conservation, monotonicity. No separate reference needed — the property *is* the check. Feasible wherever a property can be stated.
3. **Reference implementation — an independent naive twin.** The paper's own setting (slow float64 reference vs optimized kernel). The most powerful, the most expensive, and itself a place bugs hide.

**The evidence decides which one Chimera should lead with.** I sampled the 16 backlog specs. Roughly **zero** are refactors; **eleven** are additive-test or "add a small pure helper" tasks — `merge_rate`, `count_by_status`, `worst_dimensions`, `ready_slugs`, `tier_model_ids`, `outcomes_for_slug`, and so on — and the specs literally instruct *"assert its ACTUAL behavior."* That distribution is doubly telling: it is exactly the over-fit risk the paper names, **and** small pure helpers are the textbook target for property-based fuzzing. Their properties are usually obvious — `merge_rate ∈ [0,1]`; `count_by_status` sums to the total; `ready_slugs ⊆ all slugs`; `tier_model_ids` preserves the ladder order; `worst_dimensions` returns a bounded, sorted list.

So the intuitive answer inverts. The differential oracle, which sounds like the natural deepening of the B.4i regression gate, has **near-zero applicability today** (no refactors in the backlog; it stays dormant until a behavior-preserving task appears, like the lone federation-client migration). The **property-fuzz oracle has high applicability right now**, because Chimera's bread-and-butter task is precisely a small pure function checked by a few fixed assertions.

**Decision: lead with property-fuzz; keep differential as a secondary mode that auto-activates on behavior-preserving tasks.** Two honesty constraints make this safe rather than theatrical:

- **It is not a universal gate.** Unlike B.4i (which applies to any source-editing task), a correctness oracle only helps where an oracle exists. The harness must *log N/A loudly* — "no oracle available" must never be silently recorded as "verified," or the gate manufactures the very false confidence it was built to remove.
- **Fuzz must be seeded, and the failing seed recorded.** An un-seeded fuzz failure is a non-reproducible accusation — the same failure mode q004 found one layer up (a single guardrail sample lied; here, an un-seeded counterexample lies). Determinism is a correctness property of the gate itself.

**Staged build (deliberately incremental, mirroring how B.4j shipped — pure core first, wire later):**

1. A pure, injectable core — `chimera/core/fuzz_oracle.py`: `fuzz_check(fn, gen, property_fn, *, trials, seed)` and `differential_check(baseline_fn, candidate_fn, gen, *, trials, seed)`, each returning a `FuzzResult` that records `trials`, `passed`, the first counterexample, and the seed. No dependency on Hypothesis or a live agent → fully unit-testable.
2. Integration — a `property` field on `BacklogSpec`, an extra soak gate rung, and a prompt change so the agent emits a property alongside its fixed test.
3. Differential auto-activation — for tasks tagged behavior-preserving, fuzz the changed entrypoint across the base vs HEAD revisions (a direct deepening of B.4i).

The unglamorous conclusion: the paper's contribution for us is *not* "add fuzzing" — fuzzing is the easy 10%. It is the discipline of naming, per task, which oracle you actually have, and refusing to pretend you have one when you don't.
