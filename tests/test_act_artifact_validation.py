"""v4.75 (ADR 0093): natural-language artifact extraction + non-empty check.

Motivation: the 2026-05-20 v2 soak test ran a task that said
"Write all of the above to `mind/research/loop-abort-investigation.md`."
The model returned stop_reason="stop" with completed=True after two
brief rounds, but the file did not exist in the worktree. We extend
``expected_artifacts`` to also catch natural-language write targets
(no backticks) and treat zero-byte files as missing.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.act import check_artifacts, expected_artifacts


# ── natural-language extraction ─────────────────────────────────────


def test_nl_write_to_path_without_backticks():
    text = "Write all of the above to mind/research/loop-abort-investigation.md."
    assert expected_artifacts(text) == [
        "mind/research/loop-abort-investigation.md"
    ]


def test_nl_save_into_path():
    text = "Save the JSON dump into state/dump.json please."
    assert expected_artifacts(text) == ["state/dump.json"]


def test_nl_create_at_path():
    text = "Create the report at docs/report-2026-05.md and link it."
    assert expected_artifacts(text) == ["docs/report-2026-05.md"]


def test_nl_combined_with_backtick_dedupes():
    text = (
        "Write findings to `mind/x.md`, then also write findings to "
        "mind/x.md (same file)."
    )
    assert expected_artifacts(text) == ["mind/x.md"]


def test_nl_picks_up_multiple_targets():
    text = (
        "Write the trace to state/trace.log and save the summary to "
        "mind/summary.md."
    )
    assert expected_artifacts(text) == [
        "state/trace.log",
        "mind/summary.md",
    ]


# ── false-positive guards ───────────────────────────────────────────


def test_nl_ignores_paths_outside_safe_roots():
    # /etc/passwd, ~/secrets, etc. must NOT be captured.
    text = "Write the dump to /etc/passwd and to ~/secrets.txt."
    assert expected_artifacts(text) == []


def test_nl_requires_file_extension_for_unquoted_paths():
    # Bare directory mentions should not produce false matches.
    text = "Write the result to mind/research/ later."
    assert expected_artifacts(text) == []


def test_nl_ignores_overwrite_verb_prefix():
    # "overwrite" must not match the "write" anchor.
    text = "Do not overwrite mind/important.md under any circumstances."
    assert expected_artifacts(text) == []


def test_nl_ignores_unrelated_prose():
    text = "The state of the union mentions mind games but no files."
    assert expected_artifacts(text) == []


# ── non-empty check ─────────────────────────────────────────────────


def test_check_artifacts_treats_empty_file_as_missing(tmp_path: Path):
    (tmp_path / "mind").mkdir()
    (tmp_path / "mind" / "empty.md").write_text("")
    (tmp_path / "mind" / "full.md").write_text("content")
    missing = check_artifacts(
        ["mind/empty.md", "mind/full.md"], base_dir=tmp_path,
    )
    assert missing == ["mind/empty.md"]


def test_check_artifacts_treats_directory_as_missing(tmp_path: Path):
    (tmp_path / "mind" / "report").mkdir(parents=True)
    missing = check_artifacts(["mind/report"], base_dir=tmp_path)
    assert missing == ["mind/report"]


# ── regression: the original soak-test task line ────────────────────


def test_soak_test_task_line_is_caught(tmp_path: Path):
    task = (
        "Write all of the above to `mind/research/"
        "loop-abort-investigation.md`."
    )
    expected = expected_artifacts(task)
    assert expected == ["mind/research/loop-abort-investigation.md"]
    # File does not exist → still flagged missing.
    assert check_artifacts(expected, base_dir=tmp_path) == expected
