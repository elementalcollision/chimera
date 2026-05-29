"""Recursive file-count summary over the mind/ directory.

Authored by Chimera's autonomous ACT phase during the v40′ build-capability
soak (chimera-soak/v40prime-mindcount-2026-05-29-1656) — the first net-new
code Chimera wrote that landed in main. See
``mind/research/v40prime-attempt1-capstone.md`` for the convergence record.

Kept verbatim from the soak deliverable except for this docstring. The
``chimera mind count`` CLI verb (chimera/cli.py) is a thin wrapper over
``format_mind_counts``.
"""

from __future__ import annotations

from pathlib import Path


def format_mind_counts(mind_dir: Path) -> str:
    mind_dir = Path(mind_dir)
    if not mind_dir.is_dir():
        return ""
    entries = []
    for entry in sorted(mind_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            count = sum(1 for _ in entry.rglob("*") if _.is_file())
        elif entry.is_file():
            count = 1
        else:
            continue
        entries.append(f"{entry.name}: {count}")
    return "\n".join(entries) + ("\n" if entries else "")
