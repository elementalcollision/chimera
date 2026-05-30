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
    check_scope_evasion_strict,
    intended_code_path_groups,
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


# ── v4.85 (ADR 0096 amendment): multi-line / OR-list / parenthetical ─


def test_soak_v5_fixture_or_list_continuation_lines():
    """Exact text the agent received in soak v5 phase 2 — the bullet
    that completed=True with zero chimera/ writes and no scope_evasion
    firing. Both paths must be extracted.
    """
    task = (
        "Implement the fix per the sketch. Most likely files:\n"
        "`chimera/tools/loop_guard.py` (if the verdict was false-positive\n"
        "and the heuristic needs adjustment) OR `chimera/core/act.py` (if\n"
        "the verdict was correct and the response to a degenerate loop\n"
        "needs to be smarter — re-prompt, escalate, decompose)."
    )
    assert intended_code_paths(task) == [
        "chimera/tools/loop_guard.py",
        "chimera/core/act.py",
    ]


def test_extracts_path_inside_parenthetical():
    text = "Check the helper (see `chimera/core/act.py` for the impl)."
    assert intended_code_paths(text) == ["chimera/core/act.py"]


def test_extracts_path_on_continuation_line():
    text = (
        "Update the loop guard module so that\n"
        "  `chimera/tools/loop_guard.py` resets correctly."
    )
    assert intended_code_paths(text) == ["chimera/tools/loop_guard.py"]


def test_negative_backticked_symbol_is_not_a_path():
    text = "Call `should_abort_loop()` from `function_name()` in the guard."
    assert intended_code_paths(text) == []


# ── v4.85: strict check (write_targets only) ────────────────────────


def test_strict_evasion_path_in_read_command_still_unedited():
    """The soak v5 gap: agent ran ``cat chimera/...`` (path appears in
    args) but never wrote. The loose check returns clean; the strict
    check correctly flags the path as unedited.
    """
    intended = ["chimera/tools/loop_guard.py"]
    history = [
        ToolCall(
            name="shell",
            args={"command": "cat chimera/tools/loop_guard.py"},
        ),
    ]
    assert check_scope_evasion(intended, history, []) == []
    assert check_scope_evasion_strict(intended, []) == intended


def test_strict_evasion_clean_when_path_in_write_targets():
    intended = ["chimera/tools/loop_guard.py"]
    assert check_scope_evasion_strict(
        intended, ["chimera/tools/loop_guard.py"],
    ) == []


def test_strict_evasion_empty_intended_returns_empty():
    assert check_scope_evasion_strict([], ["chimera/core/act.py"]) == []


def test_strict_evasion_partial_overlap():
    intended = ["chimera/core/act.py", "chimera/tools/loop_guard.py"]
    assert check_scope_evasion_strict(
        intended, ["chimera/core/act.py"],
    ) == ["chimera/tools/loop_guard.py"]


# ── v4.105 (ADR 0109): OR-disjunction grouping ──────────────────────


def test_groups_or_disjunction_into_single_group():
    """Soak v12 fixture (task 1). 'Most likely files: X OR Y' →
    satisfying either branch satisfies the requirement.
    """
    task = (
        "Implement the fix per the sketch. Most likely files:\n"
        "`chimera/tools/loop_guard.py` (if false-positive)\n"
        "OR `chimera/core/act.py` (if correct detection)."
    )
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"chimera/tools/loop_guard.py", "chimera/core/act.py"}),
    ]


def test_groups_lowercase_or_in_parenthetical():
    """Soak v12 fixture (task 2). 'in `X` (or `Y` as appropriate)'."""
    task = (
        "Write a regression test in `tests/test_loop_guard.py` "
        "(or `tests/test_act_loop.py` as appropriate)."
    )
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"tests/test_loop_guard.py", "tests/test_act_loop.py"}),
    ]


def test_groups_singleton_for_solo_path():
    task = "Patch `chimera/core/act.py` to handle the edge case."
    assert intended_code_path_groups(task) == [
        frozenset({"chimera/core/act.py"}),
    ]


def test_groups_separate_when_sentence_break_between_paths():
    """'Edit X. Then update Y.' — both required, not an OR."""
    task = "Edit `chimera/core/act.py`. Then update `tests/test_x.py`."
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"chimera/core/act.py"}),
        frozenset({"tests/test_x.py"}),
    ]


def test_groups_separate_when_joined_by_and():
    """'X and Y' — both required, not an OR."""
    task = "Update `chimera/core/act.py` and `tests/test_x.py` together."
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"chimera/core/act.py"}),
        frozenset({"tests/test_x.py"}),
    ]


def test_groups_transitive_or_chain():
    """'X or Y or Z' collapses into a single 3-path group."""
    task = "Edit `chimera/a.py` or `chimera/b.py` or `chimera/c.py`."
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"chimera/a.py", "chimera/b.py", "chimera/c.py"}),
    ]


def test_groups_mixed_or_and_required():
    """'Edit X. Then write a test in Y or Z.' → 2 groups."""
    task = (
        "Edit `chimera/core/act.py`. Then write a regression test in "
        "`tests/test_a.py` or `tests/test_b.py`."
    )
    groups = intended_code_path_groups(task)
    assert groups == [
        frozenset({"chimera/core/act.py"}),
        frozenset({"tests/test_a.py", "tests/test_b.py"}),
    ]


def test_groups_empty_for_no_paths():
    assert intended_code_path_groups("No files named here.") == []


# ── v4.105: scope_evasion respects OR-disjunctions ──────────────────


def test_scope_evasion_satisfied_by_either_branch_loose():
    """Soak v12 task 1 reproduction: agent wrote loop_guard.py,
    never touched act.py. With OR-grouping, this is NOT evasion.
    """
    groups = [
        frozenset({"chimera/tools/loop_guard.py", "chimera/core/act.py"}),
    ]
    history = [
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "Path('chimera/tools/loop_guard.py').write_text('x')"
                ),
            },
        ),
    ]
    assert check_scope_evasion(groups, history, []) == []


def test_scope_evasion_strict_satisfied_by_either_branch():
    """Soak v12 strict-at-max_rounds reproduction. write_targets
    contains only one branch of the disjunction → satisfied.
    """
    groups = [
        frozenset({"chimera/tools/loop_guard.py", "chimera/core/act.py"}),
    ]
    assert check_scope_evasion_strict(
        groups, ["chimera/tools/loop_guard.py"],
    ) == []


def test_scope_evasion_strict_unsatisfied_when_neither_branch_written():
    groups = [
        frozenset({"chimera/tools/loop_guard.py", "chimera/core/act.py"}),
    ]
    # Reports BOTH paths so the operator sees the full disjunction.
    assert check_scope_evasion_strict(groups, []) == [
        "chimera/core/act.py",
        "chimera/tools/loop_guard.py",
    ]


def test_scope_evasion_strict_mixed_group_satisfied_and_required():
    """Required path missing, OR-group satisfied → only required reported."""
    groups = [
        frozenset({"chimera/core/act.py"}),  # required
        frozenset({"tests/test_a.py", "tests/test_b.py"}),  # either-or
    ]
    assert check_scope_evasion_strict(
        groups, ["tests/test_a.py"],  # act.py missing
    ) == ["chimera/core/act.py"]


def test_scope_evasion_accepts_flat_list_for_back_compat():
    """Existing callers passing list[str] still work — each path is a
    singleton group.
    """
    assert check_scope_evasion(
        ["chimera/core/act.py"],
        [ToolCall(name="shell", args={"command": "cat chimera/core/act.py"})],
        [],
    ) == []
    assert check_scope_evasion_strict(
        ["chimera/core/act.py"], [],
    ) == ["chimera/core/act.py"]


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


# ── v46 (commit-phase fix): intended file already ON DISK ───────────


def test_evasion_skipped_when_intended_file_exists_on_disk(tmp_path):
    """The v46 commit-phase case. Phase 2's INBOX names the file to COMMIT;
    the agent runs ``git add``/``git commit`` — no write-target, the path
    doesn't surface in this cycle's tool args. But the file IS present
    (written in phase 1). With base_dir given, that is NOT scope-evasion.
    """
    rel = "chimera/soak_report.py"
    fp = tmp_path / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("# authored phase 1\n")
    intended = [rel]
    history = [
        ToolCall(name="shell", args={"command": "git add -A && git commit -m x"}),
    ]
    # Without base_dir → legacy blob-only → flagged (the path is absent).
    assert check_scope_evasion(intended, history, []) == [rel]
    # With base_dir → file exists on disk → satisfied, not flagged.
    assert check_scope_evasion(intended, history, [], base_dir=tmp_path) == []


def test_evasion_still_fires_when_intended_file_absent_on_disk(tmp_path):
    """The real catch is preserved: an intended file that was genuinely
    never written does not exist under base_dir → still flagged, even with
    base_dir given.
    """
    intended = ["chimera/never_written.py"]
    history = [
        ToolCall(name="shell", args={"command": "git status"}),
    ]
    assert check_scope_evasion(
        intended, history, [], base_dir=tmp_path,
    ) == ["chimera/never_written.py"]


def test_evasion_empty_file_does_not_satisfy(tmp_path):
    """A zero-byte file is not a deliverable — still flagged."""
    rel = "chimera/empty.py"
    fp = tmp_path / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("")
    assert check_scope_evasion(
        [rel], [ToolCall(name="shell", args={"command": "git status"})], [],
        base_dir=tmp_path,
    ) == [rel]


def test_strict_evasion_skipped_when_intended_file_exists_on_disk(tmp_path):
    """Same fix on the strict (max_rounds-exit) path."""
    rel = "chimera/soak_report.py"
    fp = tmp_path / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("# authored phase 1\n")
    # write_targets empty + no base_dir → flagged.
    assert check_scope_evasion_strict([rel], []) == [rel]
    # base_dir given + file present → satisfied.
    assert check_scope_evasion_strict([rel], [], base_dir=tmp_path) == []


def test_strict_evasion_still_fires_when_absent_on_disk(tmp_path):
    assert check_scope_evasion_strict(
        ["chimera/never_written.py"], [], base_dir=tmp_path,
    ) == ["chimera/never_written.py"]
