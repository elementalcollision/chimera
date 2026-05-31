"""S2 / ADR 0152: the test-has-teeth mutation verifier.

A strong test must KILL most single-point mutants of the code it covers; a
vacuous test kills ~none. These tests pin that separation against a self-
contained temp module + test, plus the safety guarantees (file restored,
baseline-fails handled, cap respected).
"""

from __future__ import annotations

import sys
import textwrap

from chimera.core.mutation_teeth import (
    TeethReport,
    _generate_mutants,
    verify_test_teeth,
)

# A tiny target with arithmetic, a comparison, a bool, and string literals —
# every mutation family the verifier knows.
_MODULE = textwrap.dedent(
    '''
    def add(a, b):
        return a + b

    def is_positive(n):
        return n > 0

    def label(flag):
        return "yes" if flag else "no"

    def enabled():
        return True
    '''
).strip() + "\n"


def _write_module(tmp_path):
    (tmp_path / "mod.py").write_text(_MODULE, encoding="utf-8")
    return tmp_path / "mod.py"


# A STRONG check: exercises every function with discriminating inputs.
_STRONG = (
    "import mod; "
    "assert mod.add(2, 3) == 5; "
    "assert mod.is_positive(1) is True and mod.is_positive(-1) is False; "
    "assert mod.label(True) == 'yes' and mod.label(False) == 'no'; "
    "assert mod.enabled() is True"
)
# A VACUOUS check: imports but asserts nothing meaningful.
_WEAK = "import mod; assert True"


def _cmd(check: str) -> list[str]:
    return [sys.executable, "-c", check]


# ── _generate_mutants ───────────────────────────────────────────────


def test_generates_distinct_single_point_mutants():
    muts = _generate_mutants(_MODULE, max_mutants=20)
    descs = [d for d, _ in muts]
    assert any(d.startswith("binop") for d in descs)      # a + b
    assert any(d.startswith("compare") for d in descs)    # n > 0
    assert any(d.startswith("bool") for d in descs)       # True/False
    assert any(d.startswith("str") for d in descs)        # "yes"/"no"
    # Every mutant differs from the original and from each other's source.
    sources = [s for _, s in muts]
    assert all(s != _MODULE for s in sources)
    assert len(set(sources)) == len(sources)


def test_max_mutants_cap_respected():
    assert len(_generate_mutants(_MODULE, max_mutants=2)) == 2


def test_docstrings_are_not_mutated():
    src = textwrap.dedent(
        '''
        """Module docstring mentioning chimera/x.py — not behaviour."""

        def f():
            """Func docstring."""
            return "real"
        '''
    ).strip() + "\n"
    descs = [d for d, _ in _generate_mutants(src, max_mutants=20)]
    # Exactly ONE string site (the returned "real"), not the two docstrings.
    assert sum(1 for d in descs if d.startswith("str")) == 1


# ── verify_test_teeth: the separation ───────────────────────────────


def test_strong_test_has_teeth(tmp_path):
    target = _write_module(tmp_path)
    report = verify_test_teeth(target, _cmd(_STRONG), cwd=tmp_path)
    assert report.baseline_passed
    assert report.mutants_applied > 0
    assert report.teeth_score >= 0.8
    assert report.has_teeth()


def test_vacuous_test_has_no_teeth(tmp_path):
    target = _write_module(tmp_path)
    report = verify_test_teeth(target, _cmd(_WEAK), cwd=tmp_path)
    assert report.baseline_passed       # `assert True` passes on correct code
    assert report.mutants_applied > 0
    assert report.teeth_score == 0.0     # …and on every mutant → no teeth
    assert not report.has_teeth()
    assert len(report.survived) == report.mutants_applied


def test_baseline_failure_is_reported_not_crashed(tmp_path):
    target = _write_module(tmp_path)
    # A check that fails on the CORRECT module → can't assess teeth.
    bad = _cmd("import mod; assert mod.add(2, 3) == 999")
    report = verify_test_teeth(target, bad, cwd=tmp_path)
    assert report.baseline_passed is False
    assert report.mutants_applied == 0
    assert report.has_teeth() is False


def test_target_file_is_restored_after_run(tmp_path):
    target = _write_module(tmp_path)
    before = target.read_text(encoding="utf-8")
    verify_test_teeth(target, _cmd(_STRONG), cwd=tmp_path)
    assert target.read_text(encoding="utf-8") == before


def test_target_restored_even_if_baseline_fails(tmp_path):
    target = _write_module(tmp_path)
    before = target.read_text(encoding="utf-8")
    verify_test_teeth(target, _cmd("import mod; assert False"), cwd=tmp_path)
    assert target.read_text(encoding="utf-8") == before


# ── TeethReport ─────────────────────────────────────────────────────


def test_teeth_score_zero_when_no_mutants():
    r = TeethReport(baseline_passed=True, mutants_applied=0)
    assert r.teeth_score == 0.0
    assert r.has_teeth() is False


def test_has_teeth_threshold():
    r = TeethReport(baseline_passed=True, mutants_applied=10, mutants_killed=8)
    assert r.has_teeth(0.8) is True
    assert r.has_teeth(0.9) is False


def test_pytest_imported_module_no_stale_pyc(tmp_path):
    """Regression: a pytest test that IMPORTS the target must still kill
    mutants. Rapid rewrites + the .pyc second-granularity source-mtime header
    previously let mutants reuse the baseline's cached bytecode (all survived).
    Runs via `python -m pytest` (the case that broke), not `python -c`."""
    (tmp_path / "mod.py").write_text(_MODULE, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "import mod\n"
        "def test_add(): assert mod.add(2, 3) == 5 and mod.add(-1, 1) == 0\n"
        "def test_pos(): assert mod.is_positive(1) is True and mod.is_positive(-1) is False\n"
        "def test_lbl(): assert mod.label(True) == 'yes' and mod.label(False) == 'no'\n"
        "def test_en(): assert mod.enabled() is True\n",
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "pytest", "-q", "test_mod.py"]
    report = verify_test_teeth(tmp_path / "mod.py", cmd, cwd=tmp_path)
    assert report.baseline_passed
    assert report.teeth_score >= 0.8, report.survived
