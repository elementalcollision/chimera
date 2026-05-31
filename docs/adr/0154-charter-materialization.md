# ADR 0154 — Charter materialization: originate → build → deliver (S1 Chip 3)

**Status**: Accepted (2026-05-31). Chip 3 of S1+S2; closes the loop opened by
ADR 0152 (teeth) and ADR 0153 (self-charter).

## Context

ADR 0153 lets Chimera author a teeth-validated `CharterBundle` (acceptance test +
throwaway reference impl + scope). The remaining gap is **delivery**: turning an
approved bundle into the exact on-disk inputs the proven v46 build soak consumes,
so the agent rebuilds the target and self-commits (the full author → stage →
green → self-commit loop from the v46 arc).

## Decision

`chimera/proposals/charter_materialize.py::materialize_charter(bundle, repo_root,
prefix)` writes:

- **the acceptance test** → `tests/test_<module>.py`, with imports rewritten from
  the charter's bare `module_name` to the REAL dotted path (`chimera.<module>`)
  via `rewrite_test_imports` (`from m import X` → `from chimera.m import X`;
  `import m` → `import chimera.m as m`, word-boundary anchored);
- **a design note** → `mind/research/<prefix>-<slug>-design.md` whose
  `## READY-FOR-REMEDIATION` block carries the backticked target path — which is
  exactly what the ADR 0146 scope check parses as the commit allowlist, plus the
  `[agent]` commit-message instruction the soak contract requires.

It returns `CharterArtifacts` (target path, dotted module, test path, design
path, gate test cmd, scope allowlist). The **reference implementation is
deliberately NOT written** — that is the whole point: the soak rebuilds the
target from scratch against the test, proving the agent can build to the
self-authored spec, not just echo the reference.

`format_charter_packet` renders a one-screen review for the human-approval gate.
This module writes files and produces the packet; it does **not** launch the
soak or commit — approval is the operator's act of running the harness on the
materialized artifacts (consistent with the v46 manual-handoff discipline).

## Consequences

### Pros

- Closes **originate → build → deliver**: a self-written, teeth-validated charter
  becomes real harness inputs that flow into the proven self-commit loop. The
  first path where Chimera decides *what* to build, builds it, and ships it —
  with a human-approval gate and every v46 safety primitive intact.
- Verified against the REAL gate: a test asserts the materialized design note's
  allowlist is parsed correctly by the actual ADR 0146 scope check (not a mock),
  so the produced artifacts are accepted by the machinery downstream.
- The stripped reference impl makes the build a genuine rebuild — the agent
  cannot pass by copying the reference.

### Cons / honest disclosures

- **Import rewrite covers the common forms** (`from m import …`, `import m`), not
  every possible style (e.g. `importlib`, aliased re-exports). The charterer is
  prompted toward the simple forms; exotic imports would need a richer rewrite.
- **No auto-launch.** Materialization stops at artifacts + packet; wiring a
  `chimera charter` CLI verb and/or a runner that consumes the artifacts is a
  thin follow-up. Deliberately kept manual for the approval gate.
- **Single target module.** Multi-file charters (the S4 "multi-file changes"
  direction) are out of scope here — one new module per charter.

## Test coverage

`tests/test_charter_materialize.py` (9): import rewrite (`from`/`import`/
lookalikes untouched); on-disk layout (test written, design note written,
reference impl NOT written); `write=False` is pure; gate cmd targets the written
test; target derivation when scope is not `chimera/*.py`; **the design-note
allowlist parsed by the real ADR 0146 scope check**; the review packet fields.

## The S1+S2 arc — complete

| Chip | Capability | ADR |
|---|---|---|
| 1 | test has teeth (self-written tests are trustworthy) | 0152 |
| 2 | self-charter (originate a buildable, teeth-gated spec) | 0153 |
| 3 | materialize → feed the v46 self-commit loop | 0154 (this) |

Chimera can now decide *what* to build (self-charter), *verify the spec is
trustworthy* (teeth), and *deliver it* (materialize → build → self-commit) with a
human gate. The roadmap's "thinking" axis has its foundation.

## Next (beyond S1+S2)

- A `chimera charter "<goal>"` CLI verb: generate → validate → materialize →
  print the review packet (operator approves by launching the soak).
- Critique-and-revise on weak charters (no longer drop-only).
- S3 value/priority ranking; S4 multi-file charters; S6 real-repo shadow tasks.

## References

- [ADR 0152](./0152-test-has-teeth-mutation-verifier.md),
  [ADR 0153](./0153-self-charter-generation.md) — the chips this completes.
- [ADR 0146](./0146-pre-commit-scope-check.md) — the scope check whose allowlist
  format this materializes into.
- [ADR 0150](./0150-atomic-git-commit-tool.md) — the self-commit loop the
  materialized charter feeds.
