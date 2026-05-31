"""Self-charter generation — Chimera authors its own buildable spec (S1 / ADR 0153).

The v46 arc let Chimera BUILD a human-written charter (design note + pre-written
acceptance test + scope allowlist). S1 lets Chimera WRITE that charter for a
goal — the inversion from executing judgment to originating it.

The trust problem and its resolution: a self-written acceptance test is only safe
to build against if it actually pins behaviour (ADR 0152). But you cannot
teeth-check a test against an implementation that does not exist yet. So the
charterer emits a **reference implementation alongside the test**, the teeth
check runs against THAT (ADR 0152's ``verify_test_teeth``), and only a charter
whose test has teeth is valid. The reference impl is throwaway scaffolding to
prove the test discriminates; the charter then ships (design + test + scope) and
the build loop (the v46 self-commit machinery) re-creates the implementation from
scratch.

This module is pure orchestration + parsing + validation — every piece is
deterministically testable. The single LLM call is a thin wrapper.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a chimera.proposals ↔ chimera.core import cycle at load
    from ..core.mutation_teeth import TeethReport

# Named fenced blocks the charterer must emit.
_FENCE_RE = re.compile(r"```charter-(\w+)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class CharterBundle:
    """A self-authored, buildable charter for one goal."""

    goal: str
    module_name: str          # bare importable name, e.g. "soak_health"
    acceptance_test: str      # pytest source importing ``module_name``
    reference_impl: str       # a correct reference (throwaway; proves teeth)
    design_note: str = ""     # the what/why (optional but expected)
    scope_paths: list[str] = field(default_factory=list)  # real target path(s)


@dataclass
class CharterValidation:
    """Result of teeth-validating a charter's acceptance test."""

    ok: bool
    reason: str
    teeth: "TeethReport | None" = None


def build_charter_prompt(goal: str) -> str:
    """Prompt the charterer to emit a buildable charter for ``goal``."""
    return _CHARTER_PROMPT_TEMPLATE.format(goal=goal.strip())


def extract_charter(llm_text: str, *, goal: str) -> CharterBundle | None:
    """Parse the named fenced blocks into a :class:`CharterBundle`.

    Required blocks: ``meta`` (JSON with ``module_name`` and optional
    ``scope_paths``), ``test``, ``impl``. ``design`` is optional. Returns
    ``None`` if a required block is missing or ``meta`` is malformed —
    the caller treats that as "no usable charter this attempt".
    """
    blocks: dict[str, str] = {}
    for name, body in _FENCE_RE.findall(llm_text):
        blocks[name.lower()] = body.strip()

    meta_raw = blocks.get("meta")
    test = blocks.get("test")
    impl = blocks.get("impl")
    if not meta_raw or not test or not impl:
        return None
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        return None
    module_name = meta.get("module_name")
    if not isinstance(module_name, str) or not module_name.isidentifier():
        return None
    scope = meta.get("scope_paths")
    scope_paths = [p for p in scope if isinstance(p, str)] if isinstance(scope, list) else []

    return CharterBundle(
        goal=goal.strip(),
        module_name=module_name,
        acceptance_test=test,
        reference_impl=impl,
        design_note=blocks.get("design", ""),
        scope_paths=scope_paths,
    )


def validate_charter(
    bundle: CharterBundle,
    *,
    threshold: float = 0.8,
    max_mutants: int = 20,
    timeout: float = 120.0,
) -> CharterValidation:
    """Teeth-validate the charter's acceptance test against its reference impl.

    Writes the impl as ``<module_name>.py`` and the test as
    ``test_<module_name>.py`` into an isolated temp dir, runs the test
    (pytest), and applies :func:`verify_test_teeth`. The charter is valid iff
    the test passes on the reference impl AND kills ``threshold`` of mutants.
    Never raises — a setup/parse error returns ``ok=False`` with a reason.
    """
    from ..core.mutation_teeth import verify_test_teeth  # lazy: see import cycle note
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            impl_path = root / f"{bundle.module_name}.py"
            test_path = root / f"test_{bundle.module_name}.py"
            impl_path.write_text(bundle.reference_impl, encoding="utf-8")
            test_path.write_text(bundle.acceptance_test, encoding="utf-8")
            # Sanity: both must parse before we run anything.
            for p in (impl_path, test_path):
                try:
                    compile(p.read_text(encoding="utf-8"), str(p), "exec")
                except SyntaxError as exc:
                    return CharterValidation(False, f"unparseable {p.name}: {exc}")

            test_cmd = [sys.executable, "-m", "pytest", "-q", test_path.name]
            report = verify_test_teeth(
                impl_path, test_cmd, cwd=root,
                max_mutants=max_mutants, timeout=timeout,
            )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        return CharterValidation(False, f"validation error: {exc}")

    if not report.baseline_passed:
        return CharterValidation(
            False, "reference impl does not pass its own test", report,
        )
    if report.teeth_score < threshold:
        return CharterValidation(
            False,
            f"weak test: teeth {report.teeth_score:.2f} < {threshold:.2f} "
            f"({len(report.survived)} mutants survived)",
            report,
        )
    return CharterValidation(
        True, f"teeth {report.teeth_score:.2f} ≥ {threshold:.2f}", report,
    )


def build_charter_revision_prompt(
    goal: str, prev: CharterBundle, validation: CharterValidation,
) -> str:
    """A3: ask the charterer to strengthen a charter that failed the teeth gate.

    Feeds back the concrete failure — the reference impl not passing its own
    test, or the specific mutations the test let survive (its blind spots) — so
    the revision targets the actual weakness rather than guessing.
    """
    if validation.teeth is not None and not validation.teeth.baseline_passed:
        problem = (
            "Your reference implementation does NOT pass your own acceptance "
            "test. Fix both so the impl is correct AND the test passes on it."
        )
    else:
        survived = validation.teeth.survived if validation.teeth else []
        shown = ", ".join(survived[:8]) or "(unknown)"
        problem = (
            "Your acceptance test is too weak — it did NOT catch these mutations "
            f"of a wrong implementation: {shown}. Add discriminating assertions "
            "that would FAIL on each of those mutations."
        )
    return (
        f"You are revising a charter that failed its quality gate.\n\nGOAL: {goal}\n\n"
        f"PROBLEM: {problem}\n\n"
        f"Keep the SAME module_name (`{prev.module_name}`). Re-emit the full charter "
        f"with a stronger test (and corrected impl if needed), in EXACTLY the same "
        f"fenced blocks (charter-meta / -design / -test / -impl) and nothing else.\n\n"
        f"--- your previous acceptance test ---\n{prev.acceptance_test}\n"
        f"--- your previous reference implementation ---\n{prev.reference_impl}\n"
    )


async def generate_charter(
    goal: str,
    *,
    provider,
    model_id: str,
    threshold: float = 0.8,
    max_tokens: int = 4096,
    max_revisions: int = 1,
) -> tuple[CharterBundle | None, CharterValidation]:
    """Prompt the charterer, parse, teeth-validate, and (A3) revise on failure.

    Returns ``(bundle, validation)``. On a weak/unusable charter, up to
    ``max_revisions`` revision passes are attempted — each fed the concrete teeth
    failure (surviving mutants or baseline break). Returns as soon as a charter
    passes; otherwise the last attempt (so the caller sees the best failure).
    """
    from ..providers.base import Message

    async def _ask(prompt: str) -> CharterBundle | None:
        response = await provider.complete_with_tools(
            messages=[Message.user(prompt)], model_id=model_id, tools=[],
            max_tokens=max_tokens,
        )
        return extract_charter(getattr(response, "text", "") or "", goal=goal)

    bundle = await _ask(build_charter_prompt(goal))
    if bundle is None:
        last = CharterValidation(False, "no usable charter in model output")
    else:
        last = validate_charter(bundle, threshold=threshold)
        if last.ok:
            return bundle, last

    # A3: revise on failure, feeding back the concrete weakness.
    for _ in range(max(0, max_revisions)):
        if bundle is not None:
            revised = await _ask(build_charter_revision_prompt(goal, bundle, last))
        else:
            revised = await _ask(build_charter_prompt(goal))  # retry from scratch
        if revised is None:
            continue
        rval = validate_charter(revised, threshold=threshold)
        bundle, last = revised, rval
        if rval.ok:
            return bundle, last
    return bundle, last


_CHARTER_PROMPT_TEMPLATE = '''You are the CHARTERER for Chimera, an autonomous coding agent. Given a GOAL,
write a small, BUILDABLE charter: a single new Python module plus a pytest test
that pins its behaviour, plus a correct reference implementation.

GOAL: {goal}

Hard rules:
- Exactly ONE new module. Pick a short importable ``module_name`` (a valid Python
  identifier, e.g. ``soak_health``). The test imports it as ``module_name``.
- The acceptance test MUST pin real behaviour with discriminating assertions —
  a deliberately-wrong implementation must FAIL it. No vacuous ``assert True``.
- The reference implementation MUST pass the test and be correct.
- Keep it self-contained: standard library only unless the goal demands more.
- TESTABILITY (A2): if the goal involves nondeterminism — the current time,
  randomness, I/O, the network — design a deterministic SEAM so the behaviour is
  pinnable. Inject the clock / RNG / source as a parameter (e.g.
  ``now: float`` or ``rng: random.Random``) with a sensible default, and have the
  test pass a fixed value. Do NOT write a function whose output cannot be
  asserted exactly; that cannot pass the teeth check.

Respond with EXACTLY these fenced blocks, nothing else:

```charter-meta
{{"module_name": "your_module", "scope_paths": ["chimera/your_module.py"]}}
```
```charter-design
One paragraph: what the module does and why it is worth building.
```
```charter-test
# pytest test importing your_module — discriminating assertions
```
```charter-impl
# correct reference implementation of your_module
```
'''
