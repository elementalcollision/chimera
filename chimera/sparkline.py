"""Sparkline renderer — maps numeric sequences to Unicode block bars.

Authored by Chimera's autonomous ACT phase during the v41 build-capability
soak (chimera-soak/v41-sparkline-2026-05-29-1930) — the second net-new
module Chimera wrote that landed in main, and the first at the "moderate"
ladder rung (edge cases: empty / single / flat / negative inputs). See
``mind/research/v41-attempt1-capstone.md`` for the convergence record.

Logic kept verbatim from the soak deliverable; only this docstring added.
"""

RAMP = "▁▂▃▄▅▆▇█"  # U+2581 .. U+2588


def render_sparkline(values):
    """Return a sparkline string for *values* using 8 block levels."""
    if not values:
        return ""

    vmin = min(values)
    vmax = max(values)

    if vmin == vmax:
        # All equal (including single value) -> lowest block for each.
        return RAMP[0] * len(values)

    scale = vmax - vmin
    out_chars = []
    for v in values:
        level = round((v - vmin) / scale * 7)
        out_chars.append(RAMP[level])
    return "".join(out_chars)
