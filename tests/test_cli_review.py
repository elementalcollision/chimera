"""B1 / ADR 0160: the `chimera review` verb wires the cross-model critic.

The provider-driven adjudication is exercised live (captured in the
no-contract-autonomy state record); these tests pin the verb's deterministic
plumbing: docstring extraction (the critic's intent source) and the empty-diff
guard.
"""

from __future__ import annotations

from chimera import cli as _cli


def test_function_docstrings_extracts_module_and_function():
    src = (
        '"""Module intent."""\n'
        "def to_snake(s):\n"
        '    """Insert _ before uppercase preceded by lowercase or a digit."""\n'
        "    return s\n"
        "def helper(x):\n"
        "    return x\n"  # no docstring → omitted
    )
    out = _cli._function_docstrings(src)
    assert "(module) Module intent." in out
    assert "to_snake: Insert _ before uppercase preceded by lowercase or a digit." in out
    assert "helper" not in out  # undocumented function not listed


def test_function_docstrings_empty_on_syntax_error():
    assert _cli._function_docstrings("def (:\n bad") == ""


def test_review_empty_diff_exits_one(monkeypatch, capsys, tmp_path):
    import subprocess as _sub

    class _R:
        stdout = "   \n"
    monkeypatch.setattr(_sub, "run", lambda *a, **k: _R())
    monkeypatch.chdir(tmp_path)

    class _Args:
        target = "chimera/x.py"
        base = "main"
        test = None
        goal = None
        tier = "sonnet"

    rc = _cli._cmd_review(_Args())
    assert rc == 1
    assert "empty diff" in capsys.readouterr().err
