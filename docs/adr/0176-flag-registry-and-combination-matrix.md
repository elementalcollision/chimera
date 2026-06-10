# ADR 0176 — Central flag registry + combination test matrix

**Status:** Accepted (2026-06-10)

## Context

Chimera reads ~90 `CHIMERA_*` feature flags ad-hoc via `os.environ` across
~60 modules. There is no single source of truth, no startup validation,
and — decisively — **no test exercises any flag combination**: the suite's
flag coverage is entirely single-flag. That is exactly how the
`CHIMERA_FANOUT_BUDGET` interaction bug (zero API calls when combined with
other routing/entropy flags) escaped to live runs and had to be found by a
12-cell live characterization campaign (2026-06-09/10) instead of by CI.
Every new ADR-gated feature (0165–0174 alone added ~10 flags) widens an
unvalidated combinatorial space.

## Decision

Three additive pieces; **no call-site migration**.

### 1. Declarative registry — [`chimera/config.py`](../../chimera/config.py)

One table declaring every flag: name, kind (`bool`/`int`/`float`/`str`/
`path`/`csv`/`json`), default, description, and `interacts_with` edges.
Dynamic name families (`CHIMERA_PROPOSER_<NAME>_THRESHOLD`,
`CHIMERA_ACT_MAX_TOKENS_<TIER>`) are declared as prefixes.

Call sites deliberately keep reading `os.environ` directly. Migrating 150+
reads in one sweep would be high-risk churn with no behavioural gain; the
registry's value is the authoritative list, the validation, and the test
substrate. (A later ADR may migrate readers incrementally.)

### 2. Validation — `config.validate_env()`

Side-effect-free; returns human-readable warnings for:

- type errors (non-numeric ints/floats, malformed JSON values);
- the documented cross-flag traps: `CHIMERA_GRAPH_ENABLED` silently forced
  off by legacy `CHIMERA_AUTO_GRAPH_UPDATE_DISABLED`;
  `CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES` ignored while
  `CHIMERA_AUTO_ARCHIVE_DISABLED` is set; `CHIMERA_FANOUT_MAX_WIDTH < 1`
  deferring every parallel call; `CHIMERA_SOAK_FORCE_STALL` inert without
  `CHIMERA_SOAK_RUN_ID`; parameter flags set without their feature flag
  (`MODEL_PEER_VENDORS`, `BOLTZMANN_TEMP`).

Not yet wired into the loop's startup path — callable from CLI/tests today;
wiring a startup warning log is a small follow-up.

### 3. Enforcement + matrix tests

- [`tests/test_flag_registry.py`](../../tests/test_flag_registry.py) —
  **completeness is CI-enforced in both directions**: a `CHIMERA_*` read
  appearing in `chimera/` without a registry declaration fails, and a
  declared flag no longer read anywhere fails (no stale entries).
- [`tests/test_flag_matrix.py`](../../tests/test_flag_matrix.py) — the
  combination matrix: every single, every pair, and the all-on envelope of
  `config.HIGH_IMPACT_FLAGS` (the default-OFF togglers on the ACT hot
  path: fan-out budget, entropy signals, anneal-reheat, Boltzmann
  allocation, tool pre-filter, complexity routing, peer selection, hybrid
  search, task splitter — 47 cells) runs a scripted-provider ACT execution
  with a 3-wide parallel fan-out and asserts the one invariant whose
  violation was the live bug: **≥ 1 provider call, task completes, tools
  dispatched**. Plus a no-flag anchor cell so matrix failures are
  attributable to flags, not the harness. Whole matrix: < 1 s.

## Consequences

- This week's 12-cell live campaign is now a free, permanent CI gate; the
  FANOUT_BUDGET bug class cannot silently return (the matrix passes today
  against the #279 fix).
- Adding a flag has a declared cost: the completeness test fails until the
  flag is registered; hot-path flags belong in `HIGH_IMPACT_FLAGS`, which
  scales the matrix automatically (N axes → N·(N−1)/2 + N + 1 cells).
- The registry is documentation: `interacts_with` edges + `validate_env`
  encode what previously lived only in scattered docstrings and ADRs.
- Matrix cells assert a liveness invariant, not feature correctness —
  per-feature semantics remain each feature's own tests' job.

## Falsification / revisit triggers

- If the matrix grows past ~15 axes (>120 cells) and runtime becomes
  noticeable, switch from exhaustive pairs to a covering array.
- If a flag interaction is intentional but trips `validate_env`, encode the
  exception in the rule, not by deleting the rule.
