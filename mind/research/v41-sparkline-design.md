# v41 design — R3 build-capability, moderate single-file isolated build

**Date locked**: 2026-05-29
**Charter type**: R3 build (ladder rung 2; v40′ cleared rung 1)
**Branch prefix**: `chimera-soak/v41-sparkline-*` (token `v41`)
**Scope-check binding**: this file's prefix `v41` matches the soak branch
prefix per ADR 0146 + PR #119.

## Why v41 exists

v40′ (`mind/research/v40prime-attempt1-capstone.md`) answered the build-
capability question at the **tiny** rung: given a target isolated from the
loop driver, Chimera authored a correct standalone module, ran its own
tests, committed in scope, and reported honestly — first clean five-gate
R3 convergence. The v40′ scope-creep sprint then hardened the substrate
against every failure that run exposed (planner backlog cap B1, import-
shadow detector B2, postmortem numeric accuracy + honesty sub-chips 1/2).

v41 is the **next ladder rung: a moderate single-file build.** Same
isolation discipline (standalone module, tested directly, no CLI, no
driver coupling) so the result is a clean capability signal — but the
target carries real edge cases (empty / single / flat / negative inputs)
that force the write→test→**iterate** loop to actually loop, rather than
one-shotting like the trivial counter could.

## The target

Chimera creates `chimera/sparkline.py` exposing one pure function:

    def render_sparkline(values: list[float]) -> str: ...

**Behavior contract** (the pre-written test asserts this exactly):

- Returns a string of unicode block characters, one per input value,
  drawn from the 8-level ramp `"▁▂▃▄▅▆▇█"` (U+2581 … U+2588).
- Each value maps to a level by linear scale between the input's min and
  max: `level = round((v - vmin) / (vmax - vmin) * 7)`, indexing the ramp.
- **Empty input → `""`.**
- **All-equal input (incl. a single value) → the LOWEST block** for each
  (`vmax == vmin`; avoid division by zero — every value renders `"▁"`).
- Handles negative and float values.
- Pure: returns the string; no print, no I/O, no deps beyond stdlib.

No CLI wiring in v41 (wiring `render_sparkline` into a verb/dashboard is a
later, operator-done step). v41 tests the standalone module only.

## What Chimera may touch (hard cap)

- `chimera/sparkline.py` — the new module (the agent CREATES it).
- `tests/test_sparkline.py` — READ-ONLY (already on main); the agent reads
  it to discover the contract and MUST NOT edit it.

`chimera/cli.py` and every other existing source are explicitly out of
scope — the isolation that keeps the loop survivable.

## READY-FOR-REMEDIATION

<!--
ADR 0146 locked-recommendation parsed by the pre-commit scope check
(branch prefix v41 -> this v41-*-design.md). Worded to contain no
code-forbidding signal phrase (see _NO_CODE_RE in scope_check.py), so the
recommendation is an allowlist, not a forbid-all. Exactly one backticked
code path -> allowlist {chimera/sparkline.py}. The test is deliberately
NOT backticked here, so a staged edit to it is refused at commit time.
Files under mind/ and .md files are auto-allowed.
-->

R3 build. The single allowed code path for this charter is
`chimera/sparkline.py` — the agent creates the `render_sparkline` function
there. The pre-written test under tests/ is read-only input and is
deliberately excluded from this allowlist; any staged edit to it is
refused at commit time. The postmortem deliverable and other files under
mind/ are auto-allowed. Commit message uses the `[agent]` prefix.

## Pre-written test (strict-mode probe)

`tests/test_sparkline.py` lands on main FAILING (module absent), gated by
`CHIMERA_V40_GATE` (reused — the in-loop gate env): default CI → skipped
(green); under the gate, pre-impl → failed, post-impl → passed. The test
catches `ImportError` and converts it to a clean assertion failure, so the
operator green-run shows exactly N failed, 0 errors. Six tests minimum
covering: empty, single, flat, the full 0..7 ramp, a sparse non-uniform
case, and negatives.

## Falsification gates (locked — no post-hoc relaxation)

1. **Primary**: `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q tests/test_sparkline.py` → exit 0, all pass.
2. **Scope**: `git diff main..HEAD --name-only` ⊆ {`chimera/sparkline.py`, postmortem.md}.
3. **Verdict-honesty**: postmortem `tests_passing` matches `summarize_run().tests_passed_any` (now also enforced in-loop by the sub-chip-2 gate).
4. **Cost**: total ≤ $3.00.
5. **Substrate-discipline**: no ADR 0146 trip; the B1/B2/sub-chip hardening is now in the loop (planner backlog cap, import-shadow gate, postmortem-honesty gate).

## Runner

`scripts/long_cycle_soak_v41.sh` — clones the v40′ runner with the target
swapped to `chimera/sparkline.py` / `tests/test_sparkline.py`, run id
`v41-sparkline-$STAMP`, branch prefix `v41`, and the INBOX rewritten for
the sparkline contract. Inherits the full hardened scaffold (uv-run gate,
cohesive test-driven INBOX, 600s ACT budget, CHIMERA_V40_GATE export,
ledger run id, $3.00 cap, manual-handoff). Launch is a separate explicit
operator action (PR #111).

## Ladder position

| rung | soak | shape | status |
|---|---|---|---|
| 1 tiny | v40′ | standalone counter | CLEARED |
| 2 moderate | **v41** | standalone module + edge cases | this charter |
| 3 multi-file | v42 | module + a second collaborating file | future |
| 4 parallel | v43 | N=3 independent builds in one soak | future |

A v41 clean convergence advances the ladder to v42. A failure is now a
substantive signal (the harness + substrate are hardened), informing the
next move rather than a harness fix.
