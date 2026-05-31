"""Materialize an approved charter into the v46 self-commit harness (S1 Chip 3).

Closes the originate → build → deliver loop. Chip 2 produced a validated
``CharterBundle`` (a teeth-checked acceptance test + a throwaway reference impl +
scope). This module turns an APPROVED bundle into the exact on-disk inputs the
v46 build soak consumes:

  - the acceptance test, written to ``tests/test_<module>.py`` with its imports
    rewritten from the charter's bare ``module_name`` to the REAL dotted path
    (``chimera.<module>``) — so it imports the module the soak will build;
  - a design note under ``mind/research/`` carrying a ``READY-FOR-REMEDIATION``
    block whose backticked path IS the scope allowlist (ADR 0146 parses it);
  - the target module path (e.g. ``chimera/<module>.py``) — which is
    DELIBERATELY NOT written (the reference impl is stripped). The soak rebuilds
    it from scratch against the test, then self-commits (the v46 loop).

This module writes files and produces a human-review packet; it does NOT launch
the soak or commit — approval is the operator's act of running the harness on
the materialized artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .charter import CharterBundle


@dataclass
class CharterArtifacts:
    """On-disk inputs the build soak consumes for a materialized charter."""

    target_module_path: str   # e.g. "chimera/soak_health.py" (NOT written)
    dotted_module: str        # e.g. "chimera.soak_health"
    test_path: str            # e.g. "tests/test_soak_health.py" (written)
    design_path: str          # e.g. "mind/research/<prefix>-soak_health-design.md"
    gate_test_cmd: list[str]
    scope_allowlist: list[str] = field(default_factory=list)


def _slugify(text: str, *, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or fallback


def _dotted_from_path(target_path: str) -> str:
    """``chimera/soak_health.py`` → ``chimera.soak_health``."""
    p = target_path
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def rewrite_test_imports(test_src: str, bare: str, dotted: str) -> str:
    """Rewrite a charter test's imports of the bare module name to ``dotted``.

    ``from bare import X``  → ``from dotted import X``
    ``import bare``         → ``import dotted as bare`` (keeps ``bare.x`` refs working)

    Word-boundary anchored so ``bare_other`` / ``bare.sub`` are untouched.
    """
    if bare == dotted:
        return test_src
    src = re.sub(
        rf"(?m)^(\s*)from\s+{re.escape(bare)}\s+import\b",
        rf"\1from {dotted} import",
        test_src,
    )
    src = re.sub(
        rf"(?m)^([ \t]*)import\s+{re.escape(bare)}[ \t]*$",
        rf"\1import {dotted} as {bare}",
        src,
    )
    return src


def _target_module_path(bundle: CharterBundle) -> str:
    """The real target path: the first ``chimera/*.py`` scope path, else derived."""
    for p in bundle.scope_paths:
        if p.startswith("chimera/") and p.endswith(".py"):
            return p
    return f"chimera/{bundle.module_name}.py"


def build_design_note(bundle: CharterBundle, target_path: str, dotted: str) -> str:
    """A design note whose READY-FOR-REMEDIATION allowlist is ``target_path``.

    The backticked ``target_path`` is what ADR 0146's scope check extracts as
    the commit allowlist; the ``[agent]`` instruction matches the soak contract.
    """
    design = bundle.design_note.strip() or f"Self-charter for: {bundle.goal}"
    return (
        f"# Charter — {bundle.module_name} (self-authored)\n\n"
        f"**Goal**: {bundle.goal}\n\n"
        f"## Design\n\n{design}\n\n"
        f"## The target (ONE new file)\n\n"
        f"`{target_path}` — built to pass the pre-written acceptance test\n"
        f"`tests/test_{bundle.module_name}.py` (imports `{dotted}`). The test was\n"
        f"teeth-validated (ADR 0152/0153) before this charter was approved.\n\n"
        f"## READY-FOR-REMEDIATION\n\n"
        f"R3 build. The single allowed code path is `{target_path}` — create it,\n"
        f"importing only what the test requires. The acceptance test is read-only\n"
        f"input. The postmortem and other mind/ files are auto-allowed. The commit\n"
        f"message MUST begin with the literal `[agent]` token.\n"
    )


def materialize_charter(
    bundle: CharterBundle,
    *,
    repo_root: Path | str,
    prefix: str,
    write: bool = True,
) -> CharterArtifacts:
    """Write the test + design note for an approved charter; return the artifacts.

    The reference implementation is intentionally NOT written — the soak rebuilds
    the target module from scratch against the test. Pure path computation when
    ``write=False`` (for previewing the packet without touching disk).
    """
    root = Path(repo_root)
    target_path = _target_module_path(bundle)
    dotted = _dotted_from_path(target_path)
    test_rel = f"tests/test_{bundle.module_name}.py"
    slug = _slugify(bundle.goal, fallback=bundle.module_name)
    design_rel = f"mind/research/{prefix}-{slug}-design.md"

    artifacts = CharterArtifacts(
        target_module_path=target_path,
        dotted_module=dotted,
        test_path=test_rel,
        design_path=design_rel,
        gate_test_cmd=["uv", "run", "--extra", "dev", "pytest", "-q", test_rel],
        scope_allowlist=[target_path],
    )
    if not write:
        return artifacts

    test_src = rewrite_test_imports(bundle.acceptance_test, bundle.module_name, dotted)
    (root / test_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / test_rel).write_text(test_src.rstrip() + "\n", encoding="utf-8")
    (root / design_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / design_rel).write_text(
        build_design_note(bundle, target_path, dotted), encoding="utf-8",
    )
    return artifacts


def format_charter_packet(
    bundle: CharterBundle, artifacts: CharterArtifacts, *, teeth_score: float | None = None,
) -> str:
    """A one-screen review packet for the human-approval gate."""
    teeth = f"{teeth_score:.2f}" if teeth_score is not None else "n/a"
    return (
        f"# Charter review — {bundle.module_name}\n\n"
        f"- **Goal**: {bundle.goal}\n"
        f"- **Target** (soak will build): `{artifacts.target_module_path}`\n"
        f"- **Acceptance test**: `{artifacts.test_path}` (teeth {teeth})\n"
        f"- **Scope allowlist**: {', '.join(f'`{p}`' for p in artifacts.scope_allowlist)}\n"
        f"- **Design**: {bundle.design_note.strip() or '(none)'}\n\n"
        f"Approve by running the build soak on these artifacts. The reference "
        f"implementation was stripped — the agent rebuilds the target."
    )
