"""Format a table of rows as a left-aligned, column-aligned box table.

Provenance: authored by Chimera autonomously during the v42 build-capability
soak (R3, ladder rung 3 — multi-file build), branch
chimera-soak/v42-boxtable-2026-05-29-2253, agent commit d391018. Landed
verbatim. The agent discovered the contract by reading tests/test_boxtable.py,
hit a SyntaxError on its first build run, and self-corrected to 6/6 green. The
chimera.boxtable_cells import below is the authored cross-file boundary the
rung was designed to probe. Capstone: mind/research/v42-attempt1-capstone.md.
"""

from __future__ import annotations

from chimera.boxtable_cells import col_widths, pad_cell


def format_table(rows: list[list[str]]) -> str:
    """Return a string of the rows formatted as a left-aligned table.

    Each column's width is the maximum cell width in that column.
    Cells are padded right with spaces. Columns are separated by " | ".
    Each row ends with a newline.
    Empty input returns an empty string.
    """
    if not rows:
        return ""
    widths = col_widths(rows)
    result_lines: list[str] = []
    for row in rows:
        padded = [pad_cell(cell, widths[i]) for i, cell in enumerate(row)]
        result_lines.append(" | ".join(padded))
    return "\n".join(result_lines) + "\n"
