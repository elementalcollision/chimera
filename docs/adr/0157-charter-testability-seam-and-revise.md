# ADR 0157 — Charter testability seams (A2) + critique-and-revise (A3)

**Status**: Accepted (2026-05-31). Tier-A reliability items from the
robustness-to-production roadmap.

## Context

The self-charter gate (ADR 0153) discriminates well-specified goals from vague
ones (byte-format 0.90, IPv4 1.00; "make the codebase better" / "improve
performance" rejected). Two reliability gaps remained:

- **A2 — hard-to-test goal classes.** A goal involving the clock, randomness,
  I/O, or the network is hard to pin with a *discriminating* test, so the
  charterer would either be rejected by the teeth gate or (worse) write a
  non-deterministic test. The well-known fix is a deterministic SEAM (inject the
  clock / RNG / source), but the charterer wasn't told to use one.
- **A3 — weak charters were drop-only.** When a charter's test failed the teeth
  gate, `generate_charter` returned the failure; there was no second chance, even
  though the surviving mutants precisely describe what the test missed.

## Decision

**A2 — testability seam in the charter prompt.** The charter prompt now
instructs: for nondeterministic goals, inject a deterministic seam (e.g.
`now: float`, `rng: random.Random`) with a sensible default, and have the test
pass a fixed value — never write a function whose output cannot be asserted
exactly (it cannot pass the teeth check).

**A3 — critique-and-revise.** `generate_charter` gains `max_revisions` (default
1). On a weak/unusable first charter, it issues a revision prompt
(`build_charter_revision_prompt`) that feeds back the CONCRETE failure — the
specific surviving mutants (the test's blind spots), or that the reference impl
fails its own test — and re-validates. It returns as soon as a charter passes;
otherwise the last (best) attempt. The CLI/`run_charter` inherit the default
one revision pass.

## Consequences

### Pros

- A2: nondeterministic goals become *buildable* (a seam the test can pin)
  instead of being rejected — widening the set of goals Chimera can charter
  without weakening the teeth gate (the seam makes the test genuinely
  discriminating).
- A3: a borderline charter gets one targeted fix aimed at its actual weakness
  (the surviving mutants), rather than a blind retry — the first "iterate on its
  own judgment" loop. The teeth gate remains the hard arbiter: a revision that
  still fails is still rejected.
- Both are prompt/orchestration changes — no new trust surface; the gate is
  unchanged and authoritative.

### Cons / honest disclosures

- A3 costs one extra model call per revision on failure (bounded by
  `max_revisions`); the happy path (first charter passes) is unchanged — it
  returns immediately without revising.
- A2 is a *prompt* nudge: it raises the odds of a testable seam but does not
  guarantee one for every nondeterministic goal; the teeth gate still rejects a
  charter that ignores the guidance (which is the safe failure).
- Revision quality depends on the model using the fed-back mutants; a weak model
  may still not recover (then it is correctly rejected).

## Test coverage

`tests/test_charter_revise.py` (8): revise recovers a weak charter (2 calls);
exhausted revision returns the last failure surfaced; `max_revisions=0` never
revises (1 call); a first-try pass skips revision (1 call); recovery from an
unusable first output; the revision prompt feeds back surviving mutants and the
prior test; the baseline-failure revision path; and the base prompt contains the
A2 testability-seam instruction.

## References

- `mind/research/robustness-to-production-roadmap-2026-05-31.md` — A2/A3.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — the teeth gate (the
  arbiter A3 revises toward, and whose surviving-mutant list it feeds back).
- [ADR 0153](./0153-self-charter-generation.md) — the charterer this extends.
