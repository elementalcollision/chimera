"""Faithfulness gate (toward no-contract autonomy): is a change's behaviour
actually pinned by the suite, or could the agent alter it undetected?

Reuses the mutation verifier (ADR 0152): every surviving mutant is an unverified
behaviour. A change is "faithful" only when the suite passes on the real file
AND kills every probed mutant (threshold). These tests pin the report semantics
deterministically, and one INTEGRATION test runs the real mutator on the actual
chimera/strcase.py — the module the first live soak under-verified — proving the
gate surfaces real blind spots a green suite hides.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from chimera.core.faithfulness import FaithfulnessReport, assess_faithfulness

_MODULE = textwrap.dedent(
    """
    def add(a, b):
        return a + b

    def is_positive(n):
        return n > 0
    """
).strip() + "\n"

_STRONG = (
    "import mod; "
    "assert mod.add(2, 3) == 5; "
    "assert mod.is_positive(1) is True and mod.is_positive(-1) is False"
)
_WEAK = "import mod; assert True"


def _module(tmp_path: Path) -> Path:
    p = tmp_path / "mod.py"
    p.write_text(_MODULE, encoding="utf-8")
    return p


def _cmd(check: str) -> list[str]:
    return [sys.executable, "-c", check]


# ── report semantics ─────────────────────────────────────────────────


def test_report_faithful_property():
    r = FaithfulnessReport("x.py", baseline_passed=True, teeth_score=1.0,
                           mutants_applied=5, survived=[], threshold=1.0)
    assert r.faithful
    assert r.summary().startswith("FAITHFUL")


def test_report_under_verified_lists_blind_spots():
    r = FaithfulnessReport("x.py", baseline_passed=True, teeth_score=0.6,
                           mutants_applied=5, survived=["binop Sub→Add"],
                           threshold=1.0)
    assert r.faithful is False
    assert "UNDER-VERIFIED" in r.summary()
    assert "binop Sub→Add" in r.summary()


def test_report_unassessable_when_baseline_red():
    r = FaithfulnessReport("x.py", baseline_passed=False)
    assert r.faithful is False
    assert "UNASSESSABLE" in r.summary()


# ── assess_faithfulness against real (tmp) modules ───────────────────


def test_strong_suite_is_faithful(tmp_path):
    mod = _module(tmp_path)
    rep = assess_faithfulness(mod, _cmd(_STRONG), cwd=tmp_path)
    assert rep.baseline_passed
    assert rep.faithful, rep.summary()
    assert rep.survived == []


def test_weak_suite_is_under_verified(tmp_path):
    mod = _module(tmp_path)
    rep = assess_faithfulness(mod, _cmd(_WEAK), cwd=tmp_path)
    assert rep.baseline_passed
    assert rep.faithful is False
    assert rep.survived  # blind spots enumerated


def test_threshold_relaxation_can_pass_a_weak_suite(tmp_path):
    mod = _module(tmp_path)
    # at threshold 0.0 even a vacuous suite clears the bar (knob works)
    rep = assess_faithfulness(mod, _cmd(_WEAK), cwd=tmp_path, threshold=0.0)
    assert rep.faithful


def test_baseline_red_is_unassessable(tmp_path):
    mod = _module(tmp_path)
    rep = assess_faithfulness(mod, _cmd("import mod; assert mod.add(2,3)==999"),
                              cwd=tmp_path)
    assert rep.baseline_passed is False
    assert rep.faithful is False


# ── integration: the real module the live soak under-verified ────────


def test_real_strcase_suite_is_under_verified():
    """chimera/strcase.py + its 4 tests: the suite is GREEN but does NOT pin
    every behaviour (the index logic survives mutation). The faithfulness gate
    surfaces exactly the blind spots a passing suite hides — the empirical case
    behind this whole gate."""
    repo = Path(__file__).resolve().parents[1]
    rep = assess_faithfulness(
        repo / "chimera" / "strcase.py",
        ["uv", "run", "--extra", "dev", "pytest", "-q", "tests/test_strcase.py"],
        cwd=repo, max_mutants=40, timeout=180,
    )
    assert rep.baseline_passed, rep.summary()
    assert rep.faithful is False, "expected surviving mutants on strcase"
    assert rep.survived  # concrete unpinned behaviours to feed back to the agent
