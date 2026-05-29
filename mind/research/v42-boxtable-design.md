# v42 design — R3 build-capability, multi-file isolated build

**Date locked**: 2026-05-29
**Charter type**: R3 build (ladder rung 3; v40′/v41 cleared rungs 1–2)
**Branch prefix**: `chimera-soak/v42-boxtable-*` (token `v42`)
**Scope-check binding**: prefix `v42` matches this `v42-*-design.md` (ADR 0146 + PR #119).

## Why v42 exists

v40′ (tiny) and v41 (moderate, edge cases) both cleared cleanly and cheaply,
demonstrating that Chimera can author a correct **single** isolated module
via the write→test→iterate→commit→honest-postmortem loop. v42 is the next
rung: a **multi-file** build. The agent must author **two new files with a
working import boundary it creates** — a core helper module and a top-level
module that imports it — tested through the top module. This tests whether
build capability extends from "one file" to "coordinate an import boundary
across files I authored," the real next step in build complexity.

Same isolation discipline as v40′/v41: both targets are brand-new modules
nothing imports at load time, tested directly (no CLI, no driver coupling),
so a regression can't brick `chimera run`.

## The target (TWO new files)

**`chimera/boxtable_cells.py`** — the core helpers:

    def col_widths(rows: list[list[str]]) -> list[int]: ...
    def pad_cell(text: str, width: int) -> str: ...

- `col_widths`: per-column max cell length over all rows; `[]` for `[]`.
- `pad_cell`: `text` left-justified to `width` (`str.ljust`); if longer than
  `width`, returned unchanged (no truncation).

**`chimera/boxtable.py`** — the top module, which IMPORTS the helpers:

    from chimera.boxtable_cells import col_widths, pad_cell
    def format_table(rows: list[list[str]]) -> str: ...

- Empty `rows` → `""`.
- Otherwise: compute `col_widths`; render each row as
  `" | ".join(pad_cell(cell, w) for cell, w in zip(row, widths))`; join rows
  with `"\n"`; trailing `"\n"`. (First row is just the header — no separator
  line; keep the contract crisp.)

Worked example: `format_table([["a","bb"],["ccc","d"]])` → `"a   | bb\nccc | d \n"`.

The agent creates BOTH files; `boxtable.py` must successfully import from
`boxtable_cells.py`. That import boundary is the point of this rung.

## What Chimera may touch (hard cap)

- `chimera/boxtable.py` — new top module (CREATE).
- `chimera/boxtable_cells.py` — new helper module (CREATE).
- `tests/test_boxtable.py` — READ-ONLY (already on main); read to discover
  the contract; MUST NOT edit.

`chimera/cli.py` and every other existing source are out of scope.

## READY-FOR-REMEDIATION

<!--
ADR 0146 locked-recommendation parsed by the pre-commit scope check
(branch prefix v42 -> this v42-*-design.md). Worded to contain no
code-forbidding signal phrase (see _NO_CODE_RE). TWO backticked code paths
-> allowlist {chimera/boxtable.py, chimera/boxtable_cells.py}. The test is
NOT backticked, so a staged edit to it is refused at commit time. Files
under mind/ and .md files are auto-allowed.
-->

R3 build. The allowed code paths for this charter are
`chimera/boxtable.py` and `chimera/boxtable_cells.py` — the agent creates
both; the former imports the helpers from the latter. The pre-written test
under tests/ is read-only input and is deliberately excluded from this
allowlist; any staged edit to it is refused at commit time. The postmortem
deliverable and other files under mind/ are auto-allowed. Commit message
uses the `[agent]` prefix.

## Pre-written test (strict-mode probe)

`tests/test_boxtable.py` lands on main FAILING (modules absent), gated by
`CHIMERA_V40_GATE`: default CI → skipped; under the gate, pre-impl → failed,
post-impl → passed. Catches `ImportError` → clean assertion failure (N
failed, 0 errors). Exercises BOTH the top contract (`format_table`: empty,
single cell, 2×2, ragged header) AND the helpers directly (`col_widths`,
`pad_cell`) — so a build that omits the second file fails.

## Falsification gates (locked — no post-hoc relaxation)

1. **Primary**: `CHIMERA_V40_GATE=1 uv run --extra dev pytest -q tests/test_boxtable.py` → exit 0, all pass.
2. **Scope**: `git diff main..HEAD --name-only` ⊆ {`chimera/boxtable.py`, `chimera/boxtable_cells.py`, postmortem.md}.
3. **Verdict-honesty**: postmortem `tests_passing` matches `summarize_run().tests_passed_any` (enforced in-loop by the sub-chip-2 gate).
4. **Cost**: total ≤ $3.00.
5. **Substrate-discipline**: no ADR 0146 trip; B1/B2/sub-chip hardening live in the loop (incl. the import-shadow gate — relevant since v42 has a real cross-file import).

## Runner

`scripts/long_cycle_soak_v42.sh` — clones the v41 runner (with its corrected
phase-2 INBOX) and swaps the target to the two boxtable files / test, run id
`v42-boxtable-$STAMP`, prefix `v42`, INBOX rewritten for the two-file
contract. Phase-2 staging lists BOTH code files. Inherits the full hardened
scaffold; launch is a separate explicit operator action (PR #111).

## Ladder position

| rung | soak | result |
|---|---|---|
| 1 tiny | v40′ | CLEARED ($0.31) |
| 2 moderate | v41 | CLEARED ($0.137) |
| 3 multi-file | **v42** | this charter |
| 4 parallel | v43 | future (N=3 independent builds in one soak) |

A clean v42 convergence advances to v43 (the parallel/fan-out rung). A
failure is a substantive signal — the substrate is hardened.
