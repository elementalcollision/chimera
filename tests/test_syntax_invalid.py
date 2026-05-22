"""v4.101 (ADR 0105): syntax-validity gate on agent writes.

Soak v10 (mind/postmortems/soak-v10-2026-05-22.md, Failure section)
surfaced this gap: the agent attempted to wire `detect_ping_pong` into
chimera/core/act.py and produced a structurally invalid
`return ActResult(...verdict = detect_degenerate_loop(history)...)`
block. None of the 13 existing detectors caught the broken file; the
runner spun on identical SyntaxError tracebacks for 13 minutes before
the operator killed it.

This module tests :func:`chimera.core.act.check_syntax_valid` against
synthetic and historical fixtures, and verifies the detector is wired
into the escalation / trust / remediation pipeline.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from chimera.core.act import check_syntax_valid
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import _syntax_invalid_hint, derive_remediation_hint
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


# ── check_syntax_valid ──────────────────────────────────────────────


def test_valid_python_file_does_not_fire(tmp_path: Path) -> None:
    p = _write(tmp_path, "ok.py", "def foo():\n    return 1\n")
    assert check_syntax_valid([str(p)]) == []


def test_broken_function_signature_fires(tmp_path: Path) -> None:
    p = _write(tmp_path, "bad.py", "def foo(:\n    return 1\n")
    failures = check_syntax_valid([str(p)])
    assert len(failures) == 1
    path, msg = failures[0]
    assert path == str(p)
    assert msg  # py_compile produced something on stderr


def test_multiple_files_only_bad_flagged(tmp_path: Path) -> None:
    good = _write(tmp_path, "good.py", "x = 1\n")
    bad = _write(tmp_path, "bad.py", "def foo(:\n")
    failures = check_syntax_valid([str(good), str(bad)])
    assert [path for path, _ in failures] == [str(bad)]


def test_non_python_path_ignored(tmp_path: Path) -> None:
    p = _write(tmp_path, "notes.md", "this is not python def foo(:\n")
    assert check_syntax_valid([str(p)]) == []


def test_nonexistent_path_ignored(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.py"
    assert check_syntax_valid([str(missing)]) == []


def test_empty_write_targets_returns_empty() -> None:
    assert check_syntax_valid([]) == []


def test_v10_fixture_return_actresult_interruption(tmp_path: Path) -> None:
    """The exact failure shape from soak v10: a `return ActResult(`
    opened, then a dedented `verdict = ...` statement interrupts the
    call, then kwargs continue as if still inside the original return.

    Fixture path on disk:
    /Users/dave/chimera-soak-v10-2026-05-22-1731/chimera/core/act.py
    (around line 1524). This is the minimal reproducer.
    """
    body = (
        "def f(history, write_targets, final_text, api_call_count):\n"
        "    return ActResult(\n"
        "        task_text=task_text,\n"
        "        completed=False,\n"
        "    verdict = detect_degenerate_loop(history)\n"
        "        rounds=1,\n"
        "        write_targets=write_targets,\n"
        "    )\n"
    )
    p = _write(tmp_path, "broken_v10.py", body)
    failures = check_syntax_valid([str(p)])
    assert len(failures) == 1
    assert failures[0][0] == str(p)


# ── escalation / trust / remediation wiring ─────────────────────────


def test_syntax_invalid_is_escalating_finish_reason() -> None:
    assert "syntax_invalid" in ESCALATING_FINISH_REASONS


def test_syntax_invalid_trust_delta_is_one() -> None:
    assert FINISH_REASON_TRUST_DELTAS["syntax_invalid"] == 1


def test_syntax_invalid_hint_without_detail_is_generic() -> None:
    hint = _syntax_invalid_hint("task text", syntax_failures=None)
    assert "invalid Python syntax" in hint
    assert "Don't analyse" in hint


def test_syntax_invalid_hint_with_detail_names_path() -> None:
    failures = [("chimera/core/act.py", "SyntaxError: invalid syntax")]
    hint = _syntax_invalid_hint("task text", syntax_failures=failures)
    assert "chimera/core/act.py" in hint
    assert "SyntaxError" in hint


def test_syntax_invalid_hint_caps_at_three_paths() -> None:
    failures = [
        (f"chimera/x{i}.py", f"line {i}: SyntaxError") for i in range(5)
    ]
    hint = _syntax_invalid_hint("task text", syntax_failures=failures)
    assert "chimera/x0.py" in hint
    assert "chimera/x2.py" in hint
    # 4th + 5th are dropped
    assert "chimera/x3.py" not in hint
    assert "chimera/x4.py" not in hint


def test_derive_remediation_hint_handles_syntax_invalid() -> None:
    """The dispatch table must route syntax_invalid to its dedicated
    builder rather than falling back to _generic_hint.
    """
    hint = derive_remediation_hint("some task", "syntax_invalid")
    assert hint is not None
    assert "syntax" in hint.lower()
