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
    check_phase_fix_without_test,
    extract_write_targets_from_calls,
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


# ── v4.92: extract_write_targets_from_calls ─────────────────────────
#
# Soak v7 surfaced the root cause: write_targets was populated from ALL
# tool-call args, including reads. The path-extraction heuristic then
# treated `cat chimera/X.py` (READ) as a write. v4.91 patched the
# detector but not the population. v4.92 fixes the population.


def test_shell_reads_do_not_become_write_targets():
    """The exact v7 run-2 fixture: agent runs cat on a chimera/ source
    file. The path appears in shell args but NOTHING was written.
    """
    calls = [
        ToolCall(
            name="shell",
            args={"argv": ["cat", "chimera/tools/loop_guard.py"]},
        ),
        ToolCall(
            name="shell",
            args={"argv": ["cat", "chimera/core/act.py"]},
        ),
    ]
    assert extract_write_targets_from_calls(calls) == []


def test_code_exec_writes_do_become_write_targets():
    calls = [
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "from pathlib import Path\n"
                    "Path('mind/research/notes.md').write_text('...')\n"
                ),
            },
        ),
    ]
    paths = extract_write_targets_from_calls(calls)
    assert "mind/research/notes.md" in paths


def test_mixed_reads_and_writes_only_writes_count():
    """The mixed pattern that should land in soak v7 phase 2: agent
    reads chimera source via shell, then writes the wiring change via
    code_exec, then reads it back via shell.
    """
    calls = [
        ToolCall(name="shell", args={"argv": ["cat", "chimera/core/act.py"]}),
        ToolCall(
            name="code_exec",
            args={"code": "open('chimera/core/act.py','w').write('...')"},
        ),
        ToolCall(name="shell", args={"argv": ["cat", "chimera/core/act.py"]}),
    ]
    paths = extract_write_targets_from_calls(calls)
    # The code_exec write does land in targets; the surrounding shell
    # reads do not add anything (de-dupe + filter combine cleanly).
    assert paths == ["chimera/core/act.py"]


def test_web_fetch_and_search_do_not_become_write_targets():
    """Read-only network tools must not contribute, even if their
    fetched content happens to mention chimera/X.py paths.
    """
    calls = [
        ToolCall(
            name="http_fetch",
            args={"url": "https://example.com/chimera/core/act.py"},
        ),
        ToolCall(
            name="web_search",
            args={"query": "chimera/tools/loop_guard.py debug"},
        ),
    ]
    assert extract_write_targets_from_calls(calls) == []


def test_existing_targets_preserved_and_deduped():
    calls = [
        ToolCall(
            name="code_exec",
            args={"code": "open('mind/x.md','w').write('hi')"},
        ),
    ]
    paths = extract_write_targets_from_calls(
        calls, existing=["mind/x.md", "mind/y.md"],
    )
    assert paths == ["mind/x.md", "mind/y.md"]  # existing preserved, no dup


def test_soak_v7_end_to_end_path():
    """Reproduce the full v7 phase-1 fixture and confirm
    fix_without_test does NOT fire after v4.92 wiring.

    Agent reads three chimera/ files via shell, then writes the
    investigation doc to mind/research/. write_targets should
    contain only the mind/ path; fix_without_test must return [].
    """
    calls = [
        ToolCall(name="shell", args={"argv": ["cat", "chimera/tools/loop_guard.py"]}),
        ToolCall(name="shell", args={"argv": ["cat", "chimera/core/act.py"]}),
        ToolCall(name="shell", args={"argv": ["cat", "docs/adr/0098-ping-pong-loop-detection.md"]}),
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "open('mind/research/ping-pong-wiring-investigation.md','w')"
                    ".write('## READY-FOR-REMEDIATION\\n...')"
                ),
            },
        ),
    ]
    write_targets = extract_write_targets_from_calls(calls)
    assert "chimera/tools/loop_guard.py" not in write_targets
    assert "chimera/core/act.py" not in write_targets
    assert check_fix_without_test(calls, write_targets) == []


# ── v46 (ADR 0149): write DESTINATION, not documented content paths ──
#
# Phase 1 of the v46 re-soaks ended no_forward_progress because the
# postmortem task drew witness_rejected: the postmortem .md PROSE names
# `chimera/soak_report.py`, that path was scraped out of the write CONTENT
# into write_targets, should_witness() then surfaced the unrelated module
# to the witness panel under the postmortem charter, and it was rejected.


def test_documented_source_path_in_doc_content_is_not_a_write_target():
    """Writing a postmortem .md whose prose documents a source path must NOT
    scrape that source into write_targets (the v46 phase-1 friction)."""
    calls = [
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "from pathlib import Path\n"
                    "Path('mind/research/v46-soakreport-postmortem.md').write_text(\n"
                    "  '# Postmortem\\nBuilt chimera/soak_report.py and "
                    "tests/test_soak_report.py; 4 passed.\\n'\n"
                    ")\n"
                ),
            },
        ),
    ]
    wt = extract_write_targets_from_calls(calls)
    assert wt == ["mind/research/v46-soakreport-postmortem.md"]
    assert "chimera/soak_report.py" not in wt
    assert "tests/test_soak_report.py" not in wt
    # Downstream effect: the witness sees no foundational code to review.
    from chimera.core.witness import should_witness
    assert should_witness(wt) == []


def test_open_write_destination_extracted_not_content_paths():
    """`open('dest','w').write('… chimera/core/act.py …')` → only the dest."""
    calls = [
        ToolCall(
            name="code_exec",
            args={"code": "open('mind/x.md','w').write('see chimera/core/act.py for impl')"},
        ),
    ]
    assert extract_write_targets_from_calls(calls) == ["mind/x.md"]


def test_real_py_write_destination_still_witnessed():
    """The build task genuinely writes the module — it MUST still be a write
    target (so should_witness reviews it). The fix narrows scope, not this."""
    calls = [
        ToolCall(
            name="code_exec",
            args={
                "code": (
                    "from pathlib import Path\n"
                    "Path('chimera/soak_report.py').write_text('x = 1\\n')\n"
                ),
            },
        ),
    ]
    wt = extract_write_targets_from_calls(calls)
    assert wt == ["chimera/soak_report.py"]
    from chimera.core.witness import should_witness
    assert should_witness(wt) == ["chimera/soak_report.py"]


def test_no_write_idiom_falls_back_to_legacy_scrape():
    """Conservative fallback: a writing-tool call with no recognized write
    idiom keeps the legacy whole-blob scrape so write_targets stays populated
    for gates that depend on it."""
    calls = [
        ToolCall(
            name="code_exec",
            args={"code": "_dump(payload, 'mind/research/out.md')  # custom helper"},
        ),
    ]
    # No open()/write_text idiom → legacy scrape still finds the path.
    assert "mind/research/out.md" in extract_write_targets_from_calls(calls)


# ── v4.99 (ADR 0103): phase-scope fix_without_test ──────────────────


def test_phase_scope_empty_diff_is_clean():
    assert check_phase_fix_without_test([]) == []


def test_phase_scope_mind_only_diff_is_clean():
    # A phase that only touched investigation docs is not a "fix".
    assert check_phase_fix_without_test([
        "mind/research/loop-abort-investigation.md",
        "mind/postmortems/soak-v9-2026-05-22.md",
    ]) == []


def test_phase_scope_chimera_with_test_is_clean():
    # Both touched in the phase, even if they came from different tasks.
    assert check_phase_fix_without_test([
        "chimera/core/act.py",
        "tests/test_act_completeness.py",
    ]) == []


def test_phase_scope_chimera_without_test_flags():
    # Soak v9 fixture: phase 2 shipped chimera/core/act.py +15 lines
    # across two [agent] commits; tests/ never appeared in the cumulative
    # diff. Per-task v4.92 cleared each task individually. Phase-scope
    # check fires.
    assert check_phase_fix_without_test([
        "chimera/core/act.py",
    ]) == ["chimera/core/act.py"]


def test_phase_scope_version_module_alone_excluded():
    assert check_phase_fix_without_test(["chimera/_version.py"]) == []


def test_phase_scope_init_module_alone_excluded():
    assert check_phase_fix_without_test(["chimera/__init__.py"]) == []


def test_phase_scope_helpers_does_not_count_as_test():
    # tests/helpers.py is not a test_*.py regression — phase still flags.
    assert check_phase_fix_without_test([
        "chimera/core/act.py",
        "tests/helpers.py",
    ]) == ["chimera/core/act.py"]


def test_phase_scope_nested_test_subdir_counts():
    assert check_phase_fix_without_test([
        "chimera/core/act.py",
        "tests/integration/test_act_flow.py",
    ]) == []


def test_phase_scope_per_task_blindspot_soak_v9():
    """Reproduce the exact soak v9 Failure B fixture.

    Task A: write_targets = [chimera/core/act.py]; per-task v4.92 fires
    if the task did not name a tests/ path — but this task didn't, so
    per-task cleared. Task B: write_targets = [] (the agent claimed to
    write tests/test_loop_guard.py but never did). Per-task cleared.

    Cumulative branch diff: chimera/core/act.py touched, tests/ not.
    Phase-scope fires.
    """
    # Per-task results across the phase (simulated):
    task_a_per_task = check_fix_without_test(
        [], ["chimera/core/act.py"],
    )
    task_b_per_task = check_fix_without_test([], [])
    # NB: per-task on task A DOES return the file alone — v4.92 fires
    # within the single task that writes chimera/ without a tests/
    # sibling. The blindspot is the OTHER shape: the task text scoped
    # only the source edit and never *named* a test file, so per-task
    # write_targets correctly reflects the task's contract. The cross-
    # task case below is where phase-scope earns its keep.
    assert task_a_per_task == ["chimera/core/act.py"]
    assert task_b_per_task == []

    # The cumulative diff — phase-scope must fire.
    cumulative = ["chimera/core/act.py"]
    assert check_phase_fix_without_test(cumulative) == ["chimera/core/act.py"]


def test_phase_scope_is_an_escalating_finish_reason():
    from chimera.core.escalation import ESCALATING_FINISH_REASONS
    assert "phase_fix_without_test" in ESCALATING_FINISH_REASONS


def test_phase_scope_has_trust_delta():
    from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
    assert FINISH_REASON_TRUST_DELTAS["phase_fix_without_test"] == 1
