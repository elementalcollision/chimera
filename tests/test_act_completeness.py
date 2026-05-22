"""v4.90 (ADR 0099): fix-without-test detection.

Soak v6 (mind/postmortems/soak-v6-2026-05-22.md, Failure B) produced
a genuine code edit (chimera/tools/loop_guard.py +43 lines) but the
agent never wrote the matching test in tests/test_loop_guard.py.
artifact_missing partially caught it; the broader pattern — "agent
shipped a fix without a regression test" — gets its own detector here.
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


def test_chimera_touch_with_test_touch_is_clean():
    history = [
        ToolCall(
            name="shell",
            args={"command": "sed -i 's/foo/bar/' chimera/tools/loop_guard.py"},
        ),
        ToolCall(
            name="code_exec",
            args={"code": "open('tests/test_loop_guard.py','a').write('...')"},
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_chimera_touch_without_test_touch_flags():
    history = [
        ToolCall(
            name="shell",
            args={"command": "sed -i 's/foo/bar/' chimera/tools/loop_guard.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == [
        "chimera/tools/loop_guard.py",
    ]


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
    history = [
        ToolCall(
            name="shell",
            args={"command": "echo '__version__ = ...' > chimera/_version.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_init_module_alone_is_excluded():
    history = [
        ToolCall(
            name="shell",
            args={"command": "vim chimera/__init__.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_version_plus_real_source_still_flags_source():
    history = [
        ToolCall(
            name="shell",
            args={
                "command": (
                    "sed -i 's/x/y/' chimera/_version.py "
                    "chimera/core/act.py"
                ),
            },
        ),
    ]
    assert check_fix_without_test(history, []) == [
        "chimera/core/act.py",
    ]


def test_nested_test_subdir_also_counts():
    history = [
        ToolCall(
            name="shell",
            args={"command": "sed -i s/x/y/ chimera/core/act.py"},
        ),
        ToolCall(
            name="shell",
            args={"command": "vim tests/integration/test_act_flow.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == []


def test_test_file_not_prefixed_test_underscore_does_not_count():
    # tests/helpers.py isn't a regression test — fix should still flag.
    history = [
        ToolCall(
            name="shell",
            args={"command": "sed -i s/x/y/ chimera/core/act.py"},
        ),
        ToolCall(
            name="shell",
            args={"command": "vim tests/helpers.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == [
        "chimera/core/act.py",
    ]


def test_dedupes_multiple_mentions_of_same_source():
    history = [
        ToolCall(
            name="shell",
            args={"command": "cat chimera/core/act.py"},
        ),
        ToolCall(
            name="shell",
            args={"command": "sed -i s/x/y/ chimera/core/act.py"},
        ),
    ]
    assert check_fix_without_test(history, []) == [
        "chimera/core/act.py",
    ]


# ── soak v6 fixture ─────────────────────────────────────────────────


def test_soak_v6_fixture_loop_guard_fix_without_test():
    """The exact shape soak v6 surfaced: agent edited loop_guard.py via
    sed but never touched tests/test_loop_guard.py.
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
        ToolCall(
            name="shell",
            args={"command": "git add chimera/tools/loop_guard.py && git commit -m 'fix'"},
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
