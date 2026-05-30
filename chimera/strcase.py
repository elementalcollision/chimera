"""String case conversion utilities (v43 build-capability).

Provenance: authored by Chimera autonomously during the v43 parallel-build
soak (R3, ladder rung 4 — three independent single-file builds in one soak,
N=3), branch chimera-soak/v43-trio-2026-05-30-0052, agent commit 66a3f51.
Landed verbatim. One of three modules Chimera built concurrently; capstone
mind/research/v43-trio-capstone.md.
"""

from __future__ import annotations


def to_snake(s: str) -> str:
    """Convert CamelCase to snake_case.

    Inserts '_' before an uppercase letter when the preceding character
    is lowercase or a digit.
    """
    result: list[str] = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0 and (s[i - 1].islower() or s[i - 1].isdigit()):
            result.append("_")
        result.append(ch.lower())
    return "".join(result)


def to_camel(s: str) -> str:
    """Convert snake_case to camelCase.

    Splits on '_', keeps the first part lowercase, capitalises the rest.
    """
    if not s:
        return ""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])
