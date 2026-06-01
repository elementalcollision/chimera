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

## Amendment (differential complement, 2026-05-31)

The mutation gate's documented blind spot — a *deleted* method-call clause has no
mutation site — is now covered by `chimera/core/differential.py`. It runs the
touched function over an input corpus under BOTH the pre-change and post-change
source and reports every input whose output differs (the "behaviour delta"). A
delta is legitimate only if a test demanded it (the failing test the fix
repaired); a delta on an untested input is a candidate **silent regression** the
agent must pin with a test or revert. Contract-free: deltas come from running the
code, not a spec.

This closes the exact hole: comparing the correct `to_snake` against the agent's
`isdigit`-dropped fix over `default_string_corpus()` surfaces
`foo2Bar → foo2_bar/foo2bar`, `v2Point`, `a1B2c3` — the digit-adjacent behaviour
the mutation gate could not see. `tests/test_differential.py` (7): the headline
regression reproduction; identical-source → no delta; before/after capture; a
raised exception is observable behaviour; uncompilable source is an error marker
(not a raise); report defaults; corpus includes digit-adjacent cases.

Together, mutation (under-tested logic) + differential (deleted behaviour) cover
both directions of the faithfulness problem. Honest limits: the differential
needs an input corpus (the default covers single-string functions; general input
generation for arbitrary signatures is open), and it `exec`s the agent's own
source in an isolated namespace (not a sandbox boundary).

## Amendment (loop wiring, 2026-05-31) — `chimera faithfulness` verb

Both halves are now a first-class affordance: `chimera faithfulness --target FILE
--test TARGET [--base REF] [--strict]` runs the mutation gate (exit-affecting)
and, when `--base` is given, the differential over every single-string-arg
function (advisory; exit-affecting under `--strict`). `real_task_soak.sh`'s
phase-1 INBOX now requires it as a distinct task: "prove the change is FAITHFUL,
not just green — kill every surviving mutant with a test, and for every behaviour
delta vs base confirm a failing test demanded it; do NOT pass the suite by
deleting untested behaviour." `tests/test_cli_faithfulness.py` (5): mutation
drives the exit code; differential is advisory unless `--strict`; the
single-arg-function filter; and a real run on `chimera/strcase.py` (exit 1,
UNDER-VERIFIED).

### The enforcement/adjudication boundary (important for "no contract")

The mutation half is fully **auto-enforceable**: survivors → add tests, no
judgment needed. The differential half is **advisory by default** because it can
DETECT a behaviour change but cannot, on its own, ADJUDICATE which direction is
correct when the suite is silent (base buggy, fix dropped a clause — neither
output is "right" without intent). That adjudication is irreducibly a judgment
call. This is the key finding for the no-contract goal: contract-free
verification can get you trustworthy *detection* of faithfulness problems, but
*adjudication* of silent behaviour still needs judgment — a strong internal
critic (thrust ③) or a human reviewer. The gate surfaces the deltas precisely so
that judgment has something concrete to act on.

## Amendment (stateful characterization, 2026-06-01)

The stateful fault validation (`mind/research/validation-stateful-2026-06-01.md`)
proved the pure-function differential is BLIND on a class whose behaviour depends
on call SEQUENCE. `chimera/core/stateful_diff.py` closes that gap: `stateful_delta`
drives a class through a corpus of call SEQUENCES (a `Scenario` = an ordered
`(method, args)` list) and records a behaviour TRACE — each call's return plus a
snapshot of the auto-discovered zero-arg observer methods — then compares the
trace between base and changed source. `auto_scenarios` generates the sequences
automatically (each mutating method called N times with increasing
type-appropriate args), so it works without hand-written sequences.

Closes the exact case the validation missed: on `RunningStats` (`self._sum = x`
vs `+=`), `auto_scenarios` → `add(1,2,3)` → `mean=1.0` (buggy) vs `mean=2.0`
(correct) — a STATEFUL DELTA the pure corpus could not see.
`tests/test_stateful_diff.py` (11): catches the accumulation bug (sequence reveals
it, single-call identical); no delta on identical source; observer discovery;
never-raise; auto-scenario end-to-end. Honest limits: sample args are heuristic
(not a general fuzzer); observers must be zero-arg readable methods; this is the
PRIMITIVE — wiring into `chimera faithfulness` (auto-detect a changed class) and
covering `AugAssign` in the mutator are the next chips.

## Next

- Wire `stateful_diff` into `chimera faithfulness` (auto-detect a changed class)
  and extend the mutator to cover `AugAssign` (the validation showed `+=` is never
  mutated).
- A live proof run (fallback off) with the faithfulness step in the INBOX: does
  the agent, told to run `chimera faithfulness`, produce a *faithful* fix (keep
  the clause / add the test) instead of the silent regression?
- Thrust ③ — an internal critic that can adjudicate flagged behaviour deltas
  (the judgment the differential cannot make alone).
- Corpus generation for non-string signatures (type-driven / property-based).

## References

- [ADR 0158](./0158-real-repo-verification-gate.md) — the real-repo gate + the
  decisive run that surfaced the gate-optimization failure.
- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — `verify_test_teeth`,
  the mutation primitive this re-uses.
