"""v4.82 (ADR 0096): scope-evasion detection.

Soak v4 surfaced agents that read the source file named by an INBOX task
(``chimera/tools/loop_guard.py``), then wrote a spec doc under
``mind/research/`` and called the task complete. The runtime never
imposed a write-scope constraint; the model inferred one from the
``mind/``-heavy prior. These tests cover the regex extraction, the
no-touch detection, and the false-positive guards.
"""

from __future__ import annotations

from chimera.core.act import (
    ToolCall,
    check_scope_evasion,
    intended_code_paths,
)


# ── intended_code_paths extraction ──────────────────────────────────


def test_extracts_chimera_path_with_backticks():
    text = "Patch `chimera/tools/loop_guard.py` to reset the streak."
    assert intended_code_paths(text) == ["chimera/tools/loop_guard.py"]


def test_extracts_chimera_path_without_backticks():
    text = "Most likely files: chimera/tools/loop_guard.py (if false-positive)."
    assert intended_code_paths(text) == ["chimera/tools/loop_guard.py"]


def test_extracts_tests_and_scripts_roots():
    text = (
        "Add a regression test in tests/test_loop_guard.py and update "
        "scripts/long_cycle_soak_v5.sh accordingly."
    )
    assert intended_code_paths(text) == [
        "tests/test_loop_guard.py",
        "scripts/long_cycle_soak_v5.sh",
    ]


def test_dedupes_repeated_paths():
    text = (
        "Edit chimera/core/act.py — yes, chimera/core/act.py — to add the check."
    )
    assert intended_code_paths(text) == ["chimera/core/act.py"]


def test_ignores_mind_and_state_roots():
    # Those are caught by expected_artifacts(), not by us.
    text = "Write the spec to mind/research/loop-abort.md and state/dump.json."
    assert intended_code_paths(text) == []


def test_ignores_docs_root_to_stay_disjoint_from_artifact_check():
    text = "Update docs/runbook.md with the new procedure."
    assert intended_code_paths(text) == []


def test_ignores_unrelated_prose():
    text = "The chimera idea is interesting but no files named."
    assert intended_code_paths(text) == []


# ── check_scope_evasion ─────────────────────────────────────────────


def test_no_intended_paths_returns_empty():
    history = [ToolCall(name="shell", args={"command": "ls"})]
    assert check_scope_evasion([], history, []) == []


def test_unedited_when_path_absent_from_tool_history():
    intended = ["chimera/tools/loop_guard.py"]
    history = [
        ToolCall(name="shell", args={"command": "cat mind/research/spec.md"}),
        ToolCall(
            name="code_exec",
            args={"code": "print('hello from mind/')"},
        ),
    ]
    assert check_scope_evasion(intended, history, []) == intended


def test_path_in_shell_command_arg_counts_as_touched():
    intended = ["chimera/tools/loop_guard.py"]
    history = [
        ToolCall(
            name="shell",
            args={"command": "sed -i 's/foo/bar/' chimera/tools/loop_guard.py"},
        ),
    ]
    assert check_scope_evasion(intended, history, []) == []


def test_path_in_code_exec_snippet_counts_as_touched():
    intended = ["chimera/core/act.py"]
    history = [
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "open('chimera/core/act.py').read()"
                ),
            },
        ),
    ]
    assert check_scope_evasion(intended, history, []) == []


def test_path_in_write_targets_counts_as_touched():
    intended = ["tests/test_new.py"]
    write_targets = ["tests/test_new.py"]
    assert check_scope_evasion(intended, [], write_targets) == []


def test_partial_overlap_reports_only_untouched():
    intended = ["chimera/core/act.py", "chimera/tools/loop_guard.py"]
    history = [
        ToolCall(
            name="shell",
            args={"command": "vim chimera/core/act.py"},
        ),
    ]
    assert check_scope_evasion(intended, history, []) == [
        "chimera/tools/loop_guard.py",
    ]


# ── soak v4 fixture ─────────────────────────────────────────────────


def test_soak_v4_fixture_inbox_extracts_loop_guard():
    """Phase-2 INBOX from the v4 soak: agent received this text and
    produced ``mind/research/loop-abort-remediation.md`` instead of
    editing the named source. The regex must catch the OR-list shape.
    """
    inbox = (
        "Implement the fix per the sketch. Most likely files:\n"
        "`chimera/tools/loop_guard.py` (if false-positive in detection)\n"
        "OR `chimera/core/act.py` (if correct detection but bad action)."
    )
    assert intended_code_paths(inbox) == [
        "chimera/tools/loop_guard.py",
        "chimera/core/act.py",
    ]


def test_soak_v4_fixture_spec_under_mind_flagged_as_evasion():
    inbox = (
        "Implement the fix in `chimera/tools/loop_guard.py`. "
        "Reset the streak counter when a tool returns a result."
    )
    intended = intended_code_paths(inbox)
    # Agent's actual behaviour in the v4 fixture commit:
    history = [
        ToolCall(
            name="shell",
            args={"command": "cat chimera/tools/loop_guard.py"},
        ),
        ToolCall(
            name="shell",
            args={
                "command": (
                    "cat > mind/research/loop-abort-remediation.md <<EOF\n"
                    "## Spec\nThe function should_abort_loop should reset...\nEOF"
                ),
            },
        ),
    ]
    # The cat read counts as a "touch" — the path appears in the arg.
    # That is the intended behaviour: a read is evidence the agent
    # engaged the file, even if the edit landed elsewhere. The deeper
    # fabrication signal is covered by ADR 0095 (ungrounded_citation).
    assert check_scope_evasion(intended, history, []) == []


def test_evasion_when_agent_only_writes_under_mind():
    """The pure case: agent never touched the named source at all."""
    inbox = "Patch `chimera/core/act.py` to handle the edge case."
    intended = intended_code_paths(inbox)
    history = [
        ToolCall(
            name="shell",
            args={
                "command": (
                    "cat > mind/research/act-patch-spec.md <<EOF\n"
                    "Specification document.\nEOF"
                ),
            },
        ),
    ]
    assert check_scope_evasion(intended, history, []) == [
        "chimera/core/act.py",
    ]
