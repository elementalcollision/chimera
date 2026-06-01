"""B1 / ADR 0159: the `chimera faithfulness` verb wires the faithfulness gate.

Mutation teeth (under-tested logic) drives the exit code; the differential vs
--base (deleted behaviour) is advisory unless --strict. These tests pin the
wiring (args → assess_faithfulness / behavioral_delta → exit code) with patched
internals, plus one real end-to-end run on the actual strcase module.
"""

from __future__ import annotations

import pathlib

from chimera import cli as _cli
from chimera.core import differential as _diff
from chimera.core import faithfulness as _faith


def _patch_mutation(monkeypatch, *, faithful: bool, survived=None):
    rep = _faith.FaithfulnessReport(
        target="chimera/x.py", baseline_passed=True,
        teeth_score=1.0 if faithful else 0.5, mutants_applied=4,
        survived=survived or ([] if faithful else ["binop Sub→Add"]),
        threshold=1.0,
    )
    monkeypatch.setattr(_faith, "assess_faithfulness", lambda *a, **k: rep)


# ── mutation drives the exit code ────────────────────────────────────


def test_faithful_exits_zero(monkeypatch, capsys):
    _patch_mutation(monkeypatch, faithful=True)
    rc = _cli.main(["faithfulness", "--target", "chimera/x.py", "--test", "tests/t.py"])
    assert rc == 0
    assert "FAITHFUL" in capsys.readouterr().out


def test_under_verified_exits_one(monkeypatch, capsys):
    _patch_mutation(monkeypatch, faithful=False)
    rc = _cli.main(["faithfulness", "--target", "chimera/x.py", "--test", "tests/t.py"])
    assert rc == 1
    assert "UNDER-VERIFIED" in capsys.readouterr().out


# ── differential is advisory unless --strict ─────────────────────────


def test_differential_advisory_does_not_change_exit(monkeypatch, capsys, tmp_path):
    _patch_mutation(monkeypatch, faithful=True)  # mutation clean → exit 0
    # force a behaviour delta + a readable base source + target file
    monkeypatch.setattr(_cli, "_single_string_arg_functions", lambda src: ["f"])
    rep = _diff.DifferentialReport(fn_name="f", total=1,
                                   changed=[_diff.DeltaItem(("x",), "1", "2")])
    monkeypatch.setattr(_diff, "behavioral_delta", lambda *a, **k: rep)
    import subprocess as _sub
    monkeypatch.setattr(_cli, "Path", pathlib.Path, raising=False)
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "x.py").write_text("def f(s): return s\n")
    monkeypatch.chdir(tmp_path)

    class _R:
        returncode = 0
        stdout = "def f(s): return s + '_old'\n"
    monkeypatch.setattr(_sub, "run", lambda *a, **k: _R())

    rc = _cli.main(["faithfulness", "--target", "chimera/x.py",
                    "--test", "tests/t.py", "--base", "main"])
    err = capsys.readouterr().err
    assert "BEHAVIOUR DELTA" in err
    assert rc == 0  # advisory: delta alone does not fail

    rc_strict = _cli.main(["faithfulness", "--target", "chimera/x.py",
                           "--test", "tests/t.py", "--base", "main", "--strict"])
    assert rc_strict == 1  # --strict makes the delta exit-affecting


# ── helper ───────────────────────────────────────────────────────────


def test_single_string_arg_functions_filters_signatures():
    src = (
        "def a(x):\n    return x\n"
        "def b(x, y):\n    return x\n"
        "def c():\n    return 1\n"
        "def d(*args):\n    return args\n"
    )
    assert _cli._single_string_arg_functions(src) == ["a"]


# ── integration: the real verb on the real module ───────────────────


def test_real_strcase_is_under_verified_via_verb(capsys):
    repo = pathlib.Path(__file__).resolve().parents[1]
    import os
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        rc = _cli.main([
            "faithfulness", "--target", "chimera/strcase.py",
            "--test", "tests/test_strcase.py", "--max-mutants", "40",
        ])
    finally:
        os.chdir(cwd)
    out = capsys.readouterr().out
    assert rc == 1  # the green suite under-verifies strcase
    assert "UNDER-VERIFIED" in out


# ── multi-file (chip: multi-target faithfulness) ─────────────────────


def test_multi_target_faithful_only_if_all_pass(monkeypatch, capsys):
    """A multi-file change is faithful only if EVERY target is mutation-clean."""
    from chimera.core import faithfulness as _f

    calls = {}

    def fake(path, *a, **k):
        # first target faithful, second not
        name = str(path)
        good = "good.py" in name
        calls[name] = good
        return _f.FaithfulnessReport(
            target=name, baseline_passed=True,
            teeth_score=1.0 if good else 0.4, mutants_applied=4,
            survived=[] if good else ["binop Sub→Add"], threshold=1.0,
        )

    monkeypatch.setattr(_f, "assess_faithfulness", fake)
    rc = _cli.main(["faithfulness", "--target", "chimera/good.py",
                    "--target", "chimera/bad.py", "--test", "tests/t.py"])
    out = capsys.readouterr().out
    assert "[chimera/good.py]" in out and "[chimera/bad.py]" in out
    assert rc == 1                       # one bad → whole change unfaithful
    assert len(calls) == 2               # both files assessed


def test_multi_target_all_faithful_exits_zero(monkeypatch, capsys):
    from chimera.core import faithfulness as _f
    monkeypatch.setattr(_f, "assess_faithfulness", lambda path, *a, **k:
                        _f.FaithfulnessReport(target=str(path), baseline_passed=True,
                                              teeth_score=1.0, mutants_applied=3,
                                              survived=[], threshold=1.0))
    rc = _cli.main(["faithfulness", "--target", "chimera/a.py",
                    "--target", "chimera/b.py", "--test", "tests/t.py"])
    assert rc == 0


# ── stateful wiring (chip: stateful_diff in chimera faithfulness) ────


_RS_FIXED = (
    "class RunningStats:\n"
    "    def __init__(self):\n        self._count=0; self._sum=0.0\n"
    "    def add(self, x: float):\n        self._sum += x; self._count += 1\n"
    "    def count(self):\n        return self._count\n"
    "    def mean(self):\n        return 0.0 if self._count==0 else self._sum/self._count\n"
)
_RS_BUGGY = _RS_FIXED.replace("self._sum += x", "self._sum = x")


def test_faithfulness_surfaces_stateful_delta(monkeypatch, capsys, tmp_path):
    """A changed CLASS now gets the stateful differential (the pure corpus is
    blind on it). The fixed file vs the buggy base shows a STATEFUL DELTA."""
    from chimera.core import faithfulness as _f
    monkeypatch.setattr(_f, "assess_faithfulness", lambda *a, **k:
                        _f.FaithfulnessReport(target="x", baseline_passed=True,
                                              teeth_score=1.0, mutants_applied=4,
                                              survived=[], threshold=1.0))
    # the target on disk = the FIXED class
    (tmp_path / "chimera").mkdir()
    (tmp_path / "chimera" / "runstats.py").write_text(_RS_FIXED)
    monkeypatch.chdir(tmp_path)
    # git show base:target → the BUGGY source
    import subprocess as _sub

    class _R:
        returncode = 0
        stdout = _RS_BUGGY
    monkeypatch.setattr(_sub, "run", lambda *a, **k: _R())

    rc = _cli.main(["faithfulness", "--target", "chimera/runstats.py",
                    "--test", "tests/t.py", "--base", "main", "--strict"])
    err = capsys.readouterr().err
    assert "STATEFUL DELTA" in err
    assert "mean=" in err
    assert rc == 1   # --strict: the unjustified stateful delta fails the gate


def test_top_level_classes_detects_classes():
    assert _cli._top_level_classes(_RS_FIXED) == ["RunningStats"]
    assert _cli._top_level_classes("def f(): pass\n") == []
    assert _cli._top_level_classes("bad(:\n") == []
