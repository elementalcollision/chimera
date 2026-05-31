# ADR 0153 — Self-charter generation, teeth-gated (S1: originated judgment)

**Status**: Accepted (2026-05-31). Chip 2 of the S1+S2 direction; builds on
ADR 0152 (test-has-teeth).

## Context

The v46 arc let Chimera *build* a human-written charter (design note +
pre-written failing acceptance test + scope allowlist). S1 is the inversion:
Chimera *writes* the charter for a goal — the move from executing judgment to
originating it.

The trust hazard: a self-written acceptance test is only safe to build (and
self-commit) against if it actually pins behaviour. A vacuous test would let
Chimera "converge" on code that does nothing. ADR 0152 gives the gate
(`verify_test_teeth`), but it has a chicken-and-egg: you cannot teeth-check a
test against an implementation that does not exist yet.

## Decision

`chimera/proposals/charter.py`: the charterer emits a **reference implementation
alongside the test**, the teeth check runs against that reference, and only a
charter whose test has teeth is valid. The reference impl is throwaway
scaffolding to prove the test discriminates; the charter then ships
(design + test + scope) and the v46 self-commit loop re-creates the
implementation from scratch (Chip 3).

- `CharterBundle` — goal, `module_name`, `acceptance_test`, `reference_impl`,
  `design_note`, `scope_paths`.
- `build_charter_prompt(goal)` / `extract_charter(text, goal)` — prompt the
  model for named fenced blocks (`charter-meta` JSON, `-design`, `-test`,
  `-impl`) and parse them; returns `None` if a required block is missing or
  `meta` is malformed.
- `validate_charter(bundle, threshold=0.8)` — writes impl + test to an isolated
  temp dir, runs the test (pytest) against the impl, applies
  `verify_test_teeth`. Valid iff the reference passes its own test AND the test
  kills ≥ threshold of mutants. Never raises.
- `generate_charter(goal, provider, model_id)` — one-shot prompt → parse →
  validate. A parseable-but-weak charter is surfaced (`ok=False`), not accepted.

### Bug fixed in the dependency (ADR 0152)

Building Chip 2 surfaced a latent correctness bug in `verify_test_teeth`: a
pytest test that *imports* the target reused the baseline's cached `.pyc`
because the `.pyc` header records source mtime in **seconds**, and mutation
testing rewrites the target many times per second. Result: every mutant
silently survived (flaky — Chip 1's own `python -c` tests passed only by luck of
crossing second boundaries). Fixed by running every test subprocess with
`PYTHONDONTWRITEBYTECODE=1` (no `.pyc` ever cached → fresh compile each run),
plus a regression test exercising the pytest-import path.

## Consequences

### Pros

- Chimera can originate a buildable, *trustworthy* spec — the first "thinking"
  capability beyond executing a given charter. A weak self-written test is
  rejected before any build, closing the dangerous failure mode.
- Pure + deterministically tested: parse, teeth-gate, and orchestration each
  covered; the single LLM call is a thin wrapper tested with a stub provider.
- Hardened the ADR 0152 primitive it depends on (the pyc bug) — the dependency
  is now deterministic, not flaky.

### Cons / honest disclosures

- **Reference-impl correctness is assumed, not proven.** The teeth check proves
  the test discriminates against the reference; it does not prove the reference
  (and thus the test's notion of "correct") matches the operator's intent. That
  is what human approval (Chip 3) is for — this gate ensures the test is not
  *vacuous*, not that the goal is *right*.
- **Single-shot.** No revise-on-weak loop yet; a weak charter is surfaced and
  dropped. A critique-and-revise round is a natural follow-up.
- **Teeth floor inherits ADR 0152's limits** (fixed operator set; equivalent
  mutants). A high score means "kills the obvious mutants", not "perfect test".

## Test coverage

`tests/test_charter.py` (12): block parsing incl. missing-block / bad-meta /
non-identifier-name rejection; `validate_charter` accepts a strong charter,
rejects weak (teeth 0.0) and baseline-failing and unparseable ones;
`generate_charter` over a stub provider (strong accepted, no-charter →
`None`, weak surfaced-not-accepted); prompt includes the goal.
`tests/test_mutation_teeth.py` (+1): the pyc-stale regression via `python -m
pytest`.

## Next

- **Chip 3** — wire an approved charter into the v46 self-commit loop: strip the
  reference impl, ship (design + test + scope) into a soak harness, human
  approval gate, build → self-commit. This closes the originate → build →
  deliver loop.
- Follow-ups: critique-and-revise on weak charters; value/priority ranking of
  candidate goals (S3).

## References

- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md) — the teeth gate this
  charter must clear (and whose pyc bug this chip fixed).
- [ADR 0150](./0150-atomic-git-commit-tool.md) — the self-commit loop a teeth-
  validated charter will feed.
