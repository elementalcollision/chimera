# ADR 0152 — Test-has-teeth mutation verifier (S2: trustworthy self-authored tests)

**Status**: Accepted (2026-05-31). Chip 1 of the S1+S2 "self-charter"
direction.

## Context

The v46 arc gave Chimera genuine end-to-end autonomous delivery (author → stage
→ green → self-commit, all gates intact) — but always against a **human-written**
acceptance test. The next capability (S1) is for Chimera to author its OWN
charter: the design note, the scope allowlist, AND the acceptance test it then
builds against.

That inverts the trust model. Today the human-written test is the ground truth
that makes self-commit safe. A **self-written** test is only as trustworthy as it
is discriminating — a vacuous test (`assert True`, or one that imports but never
exercises the logic) would pass on *any* implementation, making autonomous
self-commit actively dangerous: Chimera could "converge" on code that does
nothing. So before S1 is safe, we need a deterministic gate that answers: **does
this test actually pin behaviour?**

This is the same pattern the v46 arc proved out — pair a new judgment with a
deterministic enforcement gate. Here the judgment is "Chimera wrote a test" and
the gate is "the test has teeth."

## Decision

Add `chimera/core/mutation_teeth.py::verify_test_teeth(target, test_cmd, …)` —
lightweight mutation testing:

1. **Baseline** — run the test against the correct target; it must pass (else
   teeth can't be assessed: `baseline_passed=False`, not a teeth failure).
2. **Mutate** — generate single-point AST mutants of the target: comparison-op
   swaps (`==`↔`!=`, `<`↔`>=`, …), arithmetic swaps (`+`↔`-`, …), bool flips,
   int `n→n+1`, string alteration. One change per mutant, enumerated in stable
   order, capped at `max_mutants`.
3. **Kill** — run the test against each mutant. A mutant the test FAILS on is
   *killed* (good); one it still PASSES on *survived* (a blind spot).
4. **Score** — `teeth_score = killed / applied`. `has_teeth(threshold=0.8)`
   gates on baseline + score.

**Docstrings are excluded from mutation** — they are not behaviour, so no test
can or should fail on them; mutating them only adds un-killable mutants that
depress the score. (This was found by running the verifier against the real
`chimera/soak_report.py`: 0.67 with docstring mutation, **1.0** without — the
module's docstring is a long provenance block.)

**Safety (locked):** the target file is restored unconditionally (`try/finally`)
— a crash mid-run never leaves a mutant on disk; only the target file is ever
written. Charter: never raise on a mutant.

## Consequences

### Pros

- The foundational safety primitive for S1: a self-written test can be required
  to clear a teeth threshold before Chimera is allowed to build/commit against
  it. Without it, self-authored charters are unsafe.
- Deterministic and cheap relative to value: ~N test-runs (N ≤ `max_mutants`);
  for a fast gated test (~0.4 s) that is a few seconds.
- Validated against real code: the actual `test_soak_report.py` scores **1.0**
  (13/13 killed); a vacuous `assert True` scores **0.0**. The verifier cleanly
  separates strong from worthless tests.

### Cons / honest disclosures

- **Not full mutation testing.** A small, fixed operator set — it can miss
  blind spots a richer mutator (statement deletion, operator-by-operator, AOR/
  ROR/COR families) would catch. It is a teeth FLOOR, not a completeness proof.
  A high score means "kills the obvious mutants", not "perfect".
- **Cost scales with test time × mutants.** Fine for fast unit/gated tests;
  for a slow suite, `max_mutants` and `timeout` bound it (and the caller should
  point it at the focused acceptance test, not the whole suite).
- **Equivalent mutants** (a mutation that genuinely doesn't change behaviour)
  count as survivors and slightly depress the score — accepted at this fidelity;
  the docstring exclusion removes the most common systematic case.

## Test coverage

`tests/test_mutation_teeth.py` (10): mutant generation across all four families;
docstrings not mutated; the `max_mutants` cap; a **strong** test scores ≥0.8 and
`has_teeth()`; a **vacuous** test scores 0.0 and does not; baseline-failure
reported (not crashed); the target file restored after a normal run AND after a
baseline failure; `TeethReport` score/threshold math.

## Next (S1+S2 build order)

- **Chip 2** — self-charter generation: extend the planner to emit a charter
  bundle (design note + acceptance test + scope allowlist), gated by THIS check
  (reject a charter whose test lacks teeth).
- **Chip 3** — human-approval handoff → feed the approved charter to the proven
  v46 self-commit loop.

## References

- `mind/research/why-the-agent-avoids-git-commit-2026-05-30.md` and the v46 arc
  — the validated "judgment + deterministic gate" pattern this follows.
- [ADR 0150](./0150-atomic-git-commit-tool.md) — the self-commit loop a teeth-
  gated charter will feed.
