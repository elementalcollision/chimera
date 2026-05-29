"""Helper functions for the boxtable formatting module.

Provenance: authored by Chimera autonomously during the v42 build-capability
soak (R3, ladder rung 3 — multi-file build with an authored import boundary),
branch chimera-soak/v42-boxtable-2026-05-29-2253, agent commit d391018. Landed
verbatim. Charter: mind/research/v42-boxtable-design.md; convergence record:
mind/research/v42-attempt1-capstone.md. The third+fourth net-new modules
Chimera shipped to main (after chimera/mindcount.py and chimera/sparkline.py).
"""

from __future__ import annotations


def col_widths(rows: list[list[str]]) -> list[int]:
    """Return the maximum width per column across all rows."""
    if not rows:
        return []
    ncols = max(len(r) for r in rows) if rows else 0
    widths = [0] * ncols
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    return widths


def pad_cell(text: str, width: int) -> str:
    """Right-pad *text* to *width* characters (no truncation)."""
    if len(text) >= width:
        return text
    return text + " " * (width - len(text))
