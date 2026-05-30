"""Human-friendly number formatting utilities — binary units, clamping.

Provenance: authored by Chimera autonomously during the v43 parallel-build
soak (R3, ladder rung 4, N=3), branch chimera-soak/v43-trio-2026-05-30-0052,
agent commit c857893. Landed verbatim. Capstone
mind/research/v43-trio-capstone.md.
"""

from __future__ import annotations


_UNIT_SUFFIXES = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]


def human_bytes(n: int | float) -> str:
    """Format *n* bytes as a human-readable string using binary (KiB/MiB/GiB) units.

    *  0 B         — no decimal
    *  512 B       — no decimal
    *  1.0 KiB     — one decimal place
    *  1.5 MiB     — one decimal place
    *  1.0 GiB     — one decimal place
    """
    if n < 0:
        raise ValueError(f"negative byte count: {n}")
    if n < 1024:
        return f"{n:.0f} B"
    value = float(n)
    unit_index = 0
    while value >= 1024 and unit_index < len(_UNIT_SUFFIXES) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.1f} {_UNIT_SUFFIXES[unit_index]}"


def clamp(x: int | float, lo: int | float, hi: int | float) -> int | float:
    """Return *x* constrained to the inclusive interval [*lo*, *hi*]."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
