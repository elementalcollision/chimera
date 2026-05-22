"""v4.90 + v4.91 (ADR 0099): fix-without-test detection.

Soak v6 (mind/postmortems/soak-v6-2026-05-22.md, Failure B) produced
a genuine code edit (chimera/tools/loop_guard.py +43 lines) but the
agent never wrote the matching test in tests/test_loop_guard.py.
artifact_missing partially caught it; the broader pattern — "agent
shipped a fix without a regression test" — gets its own detector here.

v4.91 contract change: the detector inspects ONLY ``write_targets``,
not ``tool_call_history`` arg values. Soak v7 surfaced a false-positive
in v4.90: phase-1 investigation tasks like "Read chimera/core/act.py"
landed the path in tool args, the regex matched, and every read got
escalated as fix_without_test → three-strikes → dead phase 1. The
corrected detector treats reading a chimera/ file as not-a-fix; only
actual writes count.
"""

from __future__ import annotations

from chimera.core.act import (
    ToolCall,
    check_fix_without_test,
)
from chimera.core.remediation import (
    _fix_without_test_hint,
    derive_remediation_hint,
)


# ── check_fix_without_test ──────────────────────────────────────────


def test_no_chimera_touch_returns_empty():
    history = [ToolCall(name="shell", args={"command": "ls mind/"})]
    assert check_fix_without_test(history, []) == []


def test_chimera_write_with_test_write_is_clean():
    assert check_fix_without_test(
        [],
        ["chimera/tools/loop_guard.py", "tests/test_loop_guard.py"],
    ) == []


def test_chimera_write_without_test_write_flags():
    assert check_fix_without_test(
        [],
        ["chimera/tools/loop_guard.py"],
    ) == ["chimera/tools/loop_guard.py"]


def test_write_targets_alone_can_signal_modification():
    assert check_fix_without_test([], ["chimera/core/act.py"]) == [
        "chimera/core/act.py",
    ]


def test_write_targets_with_test_is_clean():
    assert check_fix_without_test(
        [],
        ["chimera/core/act.py", "tests/test_act.py"],
    ) == []


def test_version_module_alone_is_excluded():
    assert check_fix_without_test([], ["chimera/_version.py"]) == []


def test_init_module_alone_is_excluded():
    assert check_fix_without_test([], ["chimera/__init__.py"]) == []


def test_version_plus_real_source_still_flags_source():
    assert check_fix_without_test(
        [],
        ["chimera/_version.py", "chimera/core/act.py"],
    ) == ["chimera/core/act.py"]


def test_nested_test_subdir_also_counts():
    assert check_fix_without_test(
        [],
        ["chimera/core/act.py", "tests/integration/test_act_flow.py"],
    ) == []


def test_test_file_not_prefixed_test_underscore_does_not_count():
    # tests/helpers.py isn't a regression test — fix should still flag.
    assert check_fix_without_test(
        [],
        ["chimera/core/act.py", "tests/helpers.py"],
    ) == ["chimera/core/act.py"]


def test_dedupes_multiple_mentions_of_same_source():
    assert check_fix_without_test(
        [],
        ["chimera/core/act.py", "chimera/core/act.py"],
    ) == ["chimera/core/act.py"]


# ── v4.91 regression: reads must NOT trigger the detector ───────────


def test_v4_91_reading_chimera_source_does_not_flag():
    """Soak v7 fixture: phase-1 INBOX asks the agent to READ
    chimera/core/act.py. The path lands in `cat` and `read_file` args
    but nothing is actually written. v4.90 falsely escalated this as
    fix_without_test; v4.91 must not.
    """
    history = [
        ToolCall(name="shell", args={"command": "cat chimera/core/act.py"}),
        ToolCall(name="shell", args={"command": "cat chimera/tools/loop_guard.py"}),
        ToolCall(
            name="code_exec",
            args={"code": "open('chimera/core/act.py').read()"},
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_v4_91_inbox_quoted_path_does_not_flag():
    """If task TEXT (not actual writes) names a chimera/ path, the
    detector must not fire. v4.90 scanned tool args including arbitrary
    strings; v4.91 looks only at write_targets.
    """
    history = [
        ToolCall(
            name="shell",
            args={
                "command": "ls mind/",
                "context": "Investigate chimera/tools/loop_guard.py heuristic",
            },
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_v4_91_write_to_mind_does_not_flag_even_if_args_mention_chimera():
    """The agent writes an investigation doc to mind/research/X.md after
    reading chimera/ source. write_targets contains only the mind/ path
    — no flag.
    """
    history = [
        ToolCall(name="shell", args={"command": "cat chimera/core/act.py"}),
        ToolCall(
            name="code_exec",
            args={"code": "open('mind/research/investigation.md','w').write('...')"},
        ),
    ]
    assert check_fix_without_test(
        history,
        ["mind/research/investigation.md"],
    ) == []


# ── soak v6 fixture ─────────────────────────────────────────────────


def test_soak_v6_fixture_loop_guard_fix_without_test():
    """The exact shape soak v6 surfaced: agent wrote loop_guard.py but
    not the test. With v4.91, the path must appear in write_targets —
    the fact that args mention it is no longer enough.
    """
    history = [
        ToolCall(
            name="shell",
            args={"command": "cat chimera/tools/loop_guard.py"},
        ),
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "from pathlib import Path\n"
                    "p = Path('chimera/tools/loop_guard.py')\n"
                    "p.write_text(p.read_text() + '\\ndef detect_ping_pong(): ...\\n')\n"
                ),
            },
        ),
    ]
    assert check_fix_without_test(history, ["chimera/tools/loop_guard.py"]) == [
        "chimera/tools/loop_guard.py",
    ]


# ── remediation hint ────────────────────────────────────────────────


def test_hint_derives_test_path_from_named_source():
    text = "Patch `chimera/tools/loop_guard.py` to add detect_ping_pong()."
    hint = _fix_without_test_hint(text)
    assert "chimera/tools/loop_guard.py" in hint
    assert "tests/test_loop_guard.py" in hint
    assert "3 test cases" in hint


def test_hint_generic_when_no_chimera_path_named():
    text = "Improve the loop guard module."
    hint = _fix_without_test_hint(text)
    assert "tests/test_<module>.py" in hint


def test_derive_remediation_hint_dispatches_fix_without_test():
    text = "Patch `chimera/core/act.py` to handle the edge case."
    hint = derive_remediation_hint(text, "fix_without_test")
    assert hint is not None
    assert "tests/test_act.py" in hint
    assert "Don't analyse" in hint


def test_fix_without_test_is_an_escalating_finish_reason():
    from chimera.core.escalation import ESCALATING_FINISH_REASONS
    assert "fix_without_test" in ESCALATING_FINISH_REASONS
