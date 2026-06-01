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
