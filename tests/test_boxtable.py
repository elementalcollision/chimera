"""Contract test for the v42 build-capability probe (multi-file).

Charter: mind/research/v42-boxtable-design.md. Operator-authored, committed
to main FAILING before the soak. Chimera's task was to create TWO new files
with a working import boundary — chimera/boxtable_cells.py (helpers) and
chimera/boxtable.py (which imports them) — so these tests pass, WITHOUT
touching chimera/cli.py or any existing source.

The build converged cleanly (v42 attempt #3, agent commit d391018; capstone
mind/research/v42-attempt1-capstone.md). With both modules now on main the
CHIMERA_V40_GATE skipif is removed so these 6 contract tests run in CI.

These assertions ARE the spec. The test exercises BOTH the top-level
format_table AND the helpers directly, so a build that omits the second file
(or breaks the import) fails. Harness: lazy imports convert a missing module
to a clean assertion failure (N failed, never a collection error).
"""

from __future__ import annotations

import pytest


def _format_table(rows):
    try:
        from chimera.boxtable import format_table
    except ImportError as exc:  # top module / its import not ready
        pytest.fail(f"chimera.boxtable.format_table not importable: {exc}")
    return format_table(rows)


def _helpers():
    try:
        from chimera.boxtable_cells import col_widths, pad_cell
    except ImportError as exc:  # helper module not ready
        pytest.fail(f"chimera.boxtable_cells helpers not importable: {exc}")
    return col_widths, pad_cell


# ── top-level contract (chimera/boxtable.py) ─────────────────

def test_empty_is_empty_string():
    assert _format_table([]) == ""


def test_single_cell():
    assert _format_table([["x"]]) == "x\n"


def test_two_by_two():
    assert _format_table([["a", "bb"], ["ccc", "d"]]) == "a   | bb\nccc | d \n"


def test_ragged_header():
    rows = [["id", "name"], ["1", "alice"], ["20", "bo"]]
    assert _format_table(rows) == "id | name \n1  | alice\n20 | bo   \n"


# ── helper contract (chimera/boxtable_cells.py) ──────────────

def test_col_widths():
    col_widths, _ = _helpers()
    assert col_widths([["id", "name"], ["1", "alice"], ["20", "bo"]]) == [2, 5]
    assert col_widths([]) == []


def test_pad_cell():
    _, pad_cell = _helpers()
    assert pad_cell("hi", 5) == "hi   "
    # Longer than width -> returned unchanged (no truncation).
    assert pad_cell("toolong", 3) == "toolong"
