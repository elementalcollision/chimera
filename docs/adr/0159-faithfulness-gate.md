# ADR 0159 — Faithfulness gate (toward production-worthy autonomy without contracts)

**Status**: Accepted (2026-05-31). First step of the "no-contract" roadmap —
making the agent's self-verification trustworthy enough to drop human-written
acceptance tests.

## Context

The B1 decisive run (ADR 0158) proved Chimera can autonomously fix a real
failing test and self-commit it with no harness fallback. It also exposed the
core risk of test-gated autonomy, with evidence: asked to fix `to_snake`, the
agent made the failing tests pass by the cheapest path — **dropping** an
untested clause (`or s[i-1].isdigit()`). ruff + pytest were green, so by the
loop's contract the change was "correct," yet it silently regressed behaviour
the suite didn't guard. This is Goodhart's law: when an incomplete suite is the
target, it gets satisfied by removing behaviour it doesn't cover.

This gets strictly worse without contracts — if no human writes the test, there
is nothing pinning behaviour at all. So before Chimera can produce
production-worthy code without contracts, its *self*-verification must be
un-gameable: a change is only "verified" if the suite actually pins what the
change touched.

## Decision

`chimera/core/faithfulness.py::assess_faithfulness(target_path, test_cmd, …)`:
re-use the mutation verifier (ADR 0152, `verify_test_teeth`) as a faithfulness
gate on a change. It runs the suite on the real file (baseline), then mutates
the file one site at a time; **every surviving mutant is an unverified
behaviour** — a blind spot the change could alter undetected. A change is
`faithful` only when the baseline is green AND every probed mutant is killed
(`teeth_score >= threshold`, default 1.0). The blind spots are derived from the
code itself — **no human-written contract is involved** — and they are returned
so the agent can close them by authoring discriminating tests.

## Consequences

### Pros

- Directly attacks the witnessed failure class: a green-but-incomplete suite no
  longer counts as "verified." The agent must drive the touched file to
  mutation-coverage, which forces it to author the tests the gate exposes are
  missing — moving verification authorship to the agent (the no-contract
  direction).
- Reuses a proven, deterministic primitive (`verify_test_teeth`); the new
  surface is a thin framing layer plus the report semantics.
- Empirically grounded: on the actual `chimera/strcase.py` + its 4 tests the
  gate reports `teeth_score 0.73` with 3 surviving mutants (the `i > 0` / `i-1`
  index logic is unpinned) — real blind spots a passing suite hides.

### Cons / honest disclosures

- **Necessary, not sufficient.** The AST mutator probes operators, constants,
  boolean ops, and indices — it does NOT probe method-call branches (e.g.
  `.isdigit()`). So it will not, on its own, flag a *deleted* method-call clause
  (the exact strcase regression). It raises the floor and forces test-authorship
  for under-tested LOGIC; catching behaviour **deletion** needs a complementary
  differential / characterization check (the next step).
- **Cost.** Mutation testing runs the suite once per mutant; callers should cap
  `max_mutants` and narrow `test_cmd` to the affected tests.
- **Whole-file scope.** This first cut assesses the whole target file; a change
  should arguably only be held to the behaviours NEAR its diff. Diff-scoped
  mutant selection is a refinement.
- This is the GATE primitive, not yet wired into the real-task loop as an
  acceptance criterion (the next chip).

## Test coverage

`tests/test_faithfulness.py` (8): report `faithful`/`summary` semantics
(faithful / under-verified-with-blind-spots / unassessable); a strong suite is
faithful with no survivors; a weak suite is under-verified with enumerated
blind spots; the threshold knob; a red baseline is unassessable; and an
**integration** test running the real mutator on `chimera/strcase.py` proving
the green suite is under-verified.

## Next

- Wire `assess_faithfulness` into `real_task_soak.sh` / the ACT gate as an
  acceptance criterion: a change is not "done" until the touched file is
  mutation-clean (or the agent has authored tests that kill the survivors).
- Complement with a differential / characterization check to catch behaviour
  DELETION (the method-call-clause gap this gate cannot see).

## References

- [ADR 0158](./0158-real-repo-verification-gate.md) — the real-repo gate + the
  decisive run that surfaced the gate-optimization failure.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — `verify_test_teeth`,
  the mutation primitive this re-uses.
