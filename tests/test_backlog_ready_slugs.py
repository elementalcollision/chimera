"""Tests for ready_slugs() — the allowlist of actionable task ids."""

from __future__ import annotations

from pathlib import Path

from chimera.core.backlog import backlog_dir, ready_slugs


def _write(d: Path, name: str, text: str) -> Path:
    """Helper: create a file in directory d with the given text."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


def test_ready_slugs_empty_backlog(tmp_path):
    """Missing backlog dir → empty list, not an error."""
    mind = tmp_path / "mind"
    assert ready_slugs(mind) == []


def test_ready_slugs_single_valid_spec(tmp_path):
    """One valid, not-done spec → its slug is returned."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "fix-utcnow.md", """---
goal: Fix the deprecated utcnow call
files: chimera/core/time.py
---
Replace utcnow() with timezone-aware now(UTC).
""")
    slugs = ready_slugs(mind)
    assert slugs == ["fix-utcnow"]


def test_ready_slugs_excludes_done_specs(tmp_path):
    """Specs with done: true are excluded from the ready list."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "01-done.md", """---
goal: Already completed task
files: a.py
done: true
---
""")
    _write(d, "02-ready.md", """---
goal: Actionable task
files: b.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["02-ready"]
    assert "01-done" not in slugs


def test_ready_slugs_excludes_invalid_specs(tmp_path):
    """Invalid specs (missing goal or files) are excluded."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    # Invalid: missing goal
    _write(d, "01-bad.md", """---
files: a.py
---
""")
    # Valid
    _write(d, "02-good.md", """---
goal: Good task
files: b.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["02-good"]
    assert "01-bad" not in slugs


def test_ready_slugs_mixed_statuses(tmp_path):
    """Mix of done, invalid, and valid → only valid not-done returned."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "01-done.md", """---
goal: Done task
files: a.py
done: true
---
""")
    _write(d, "02-invalid.md", """---
files: b.py
---
""")
    _write(d, "03-ready-a.md", """---
goal: Ready task A
files: c.py
---
""")
    _write(d, "04-ready-b.md", """---
goal: Ready task B
files: d.py
---
""")
    slugs = ready_slugs(mind)
    # Only the two valid, not-done specs
    assert slugs == ["03-ready-a", "04-ready-b"]
    assert "01-done" not in slugs
    assert "02-invalid" not in slugs


def test_ready_slugs_ordering_is_filename_sorted(tmp_path):
    """Slugs are returned in filename order (matching list_specs)."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    # Write in non-alphabetical order
    _write(d, "zebra.md", """---
goal: Z task
files: z.py
---
""")
    _write(d, "alpha.md", """---
goal: A task
files: a.py
---
""")
    _write(d, "middle.md", """---
goal: M task
files: m.py
---
""")
    slugs = ready_slugs(mind)
    # Sorted by filename
    assert slugs == ["alpha", "middle", "zebra"]


def test_ready_slugs_ignores_readme_and_dotfiles(tmp_path):
    """README.md and .dotfiles are not treated as specs."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "README.md", "# Backlog documentation\nNo frontmatter here.")
    _write(d, ".draft.md", """---
goal: Work in progress
files: wip.py
---
""")
    _write(d, "real-task.md", """---
goal: Real task
files: real.py
---
""")
    slugs = ready_slugs(mind)
    # Only the real task; README and .draft are ignored
    assert slugs == ["real-task"]


def test_ready_slugs_frontmatter_not_a_mapping_is_invalid(tmp_path):
    """YAML frontmatter that is not a dict → invalid → excluded."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "list-yaml.md", """---
- just a list
- not a mapping
---
""")
    _write(d, "valid.md", """---
goal: Valid task
files: v.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["valid"]
    assert "list-yaml" not in slugs


def test_ready_slugs_no_frontmatter_is_invalid(tmp_path):
    """Plain markdown without frontmatter → invalid → excluded."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "plain.md", "Just some notes, no frontmatter.\n")
    _write(d, "valid.md", """---
goal: Valid task
files: v.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["valid"]
    assert "plain" not in slugs


def test_ready_slugs_returns_list_not_iterator(tmp_path):
    """Return type is a list, not a generator or other lazy type."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "task.md", """---
goal: A task
files: a.py
---
""")
    slugs = ready_slugs(mind)
    assert isinstance(slugs, list)
    assert len(slugs) == 1
    assert slugs[0] == "task"


def test_ready_slugs_multiple_files_field(tmp_path):
    """Specs with multiple files in the allowlist are still valid."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "multi.md", """---
goal: Refactor multiple modules
files: chimera/core/a.py chimera/core/b.py tests/test_x.py
test: tests/test_x.py
base: main
---
Refactor across these files.
""")
    slugs = ready_slugs(mind)
    assert slugs == ["multi"]


def test_ready_slugs_files_as_yaml_list(tmp_path):
    """Files specified as a YAML list (not space-separated) are valid."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "list-files.md", """---
goal: Task with list-style files
files:
  - a.py
  - b.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["list-files"]


def test_ready_slugs_missing_files_field_is_invalid(tmp_path):
    """Spec with goal but no files field → invalid → excluded."""
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "no-files.md", """---
goal: Missing files field
---
""")
    _write(d, "valid.md", """---
goal: Valid task
files: v.py
---
""")
    slugs = ready_slugs(mind)
    assert slugs == ["valid"]
    assert "no-files" not in slugs


def test_parse_spec_error_message_missing_goal(tmp_path):
    """Pin exact error message for missing goal field."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "bad.md"
    p.write_text("""---
files: a.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert not spec.valid
    assert spec.errors == ("missing required `goal`",)


def test_parse_spec_error_message_missing_files(tmp_path):
    """Pin exact error message for missing files field."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "bad.md"
    p.write_text("""---
goal: Some task
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert not spec.valid
    assert spec.errors == ("missing required `files` (space-separated allowlist)",)


def test_parse_spec_error_no_frontmatter(tmp_path):
    """Pin exact error message for missing frontmatter."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "plain.md"
    p.write_text("Just text, no frontmatter.\n", encoding="utf-8")
    spec = parse_spec(p)
    assert not spec.valid
    assert spec.errors == ("no YAML frontmatter (expected a leading `---` block)",)


def test_parse_spec_error_not_a_mapping(tmp_path):
    """Pin exact error message when frontmatter is not a dict."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "list.md"
    p.write_text("""---
- just a list
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert not spec.valid
    assert spec.errors == ("frontmatter is not a mapping",)


def test_parse_spec_default_base_is_main(tmp_path):
    """When base is omitted, it defaults to 'main'."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: A task
files: a.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert spec.base == "main"


def test_parse_spec_default_done_is_false(tmp_path):
    """When done is omitted, it defaults to False."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: A task
files: a.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert spec.done is False


def test_parse_spec_done_true(tmp_path):
    """When done: true, spec.done is True."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: A task
files: a.py
done: true
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert spec.done is True


def test_task_env_contains_required_keys(tmp_path):
    """task_env() returns TASK_GOAL, TASK_FILES, TASK_BASE."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Do the thing
files: a.py b.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    env = spec.task_env()
    assert env["TASK_GOAL"] == "Do the thing"
    assert env["TASK_FILES"] == "a.py b.py"
    assert env["TASK_BASE"] == "main"


def test_task_env_includes_task_test_when_present(tmp_path):
    """task_env() includes TASK_TEST when test field is set."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Do the thing
files: a.py
test: tests/test_x.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    env = spec.task_env()
    assert env["TASK_TEST"] == "tests/test_x.py"


def test_task_env_omits_task_test_when_absent(tmp_path):
    """task_env() does NOT include TASK_TEST when test field is absent."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Do the thing
files: a.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    env = spec.task_env()
    assert "TASK_TEST" not in env


def test_task_env_includes_repo_and_verify_cmd(tmp_path):
    """task_env() includes TASK_REPO and TASK_VERIFY_CMD when set."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Do the thing
files: a.py
repo: owner/name
verify_cmd: pytest tests/
---
""", encoding="utf-8")
    spec = parse_spec(p)
    env = spec.task_env()
    assert env["TASK_REPO"] == "owner/name"
    assert env["TASK_VERIFY_CMD"] == "pytest tests/"


def test_backlog_dir_uses_backlog_dirname(tmp_path):
    """backlog_dir() returns mind_dir / 'backlog'."""
    from chimera.core.backlog import backlog_dir
    result = backlog_dir(tmp_path)
    assert result == tmp_path / "backlog"


def test_count_by_status_empty_backlog(tmp_path):
    """count_by_status returns {"ready": 0, "done": 0, "invalid": 0} for empty."""
    from chimera.core.backlog import count_by_status
    result = count_by_status(tmp_path)
    assert result == {"ready": 0, "done": 0, "invalid": 0}


def test_count_by_status_mixed(tmp_path):
    """count_by_status correctly categorizes specs."""
    from chimera.core.backlog import count_by_status, backlog_dir
    d = backlog_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    # Ready
    (d / "ready.md").write_text("""---
goal: Ready task
files: a.py
---
""", encoding="utf-8")
    # Done
    (d / "done.md").write_text("""---
goal: Done task
files: b.py
done: true
---
""", encoding="utf-8")
    # Invalid
    (d / "invalid.md").write_text("""---
files: c.py
---
""", encoding="utf-8")
    result = count_by_status(tmp_path)
    assert result == {"ready": 1, "done": 1, "invalid": 1}


def test_select_next_with_claimed_slugs(tmp_path):
    """select_next skips specs whose slug is in claimed_slugs."""
    from chimera.core.backlog import select_next, backlog_dir
    d = backlog_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "01-claimed.md").write_text("""---
goal: Already claimed
files: a.py
---
""", encoding="utf-8")
    (d / "02-available.md").write_text("""---
goal: Available
files: b.py
---
""", encoding="utf-8")
    spec = select_next(tmp_path, claimed_slugs=frozenset(["01-claimed"]))
    assert spec is not None
    assert spec.slug == "02-available"


def test_select_next_no_actionable(tmp_path):
    """select_next returns None when all specs are done or invalid."""
    from chimera.core.backlog import select_next, backlog_dir
    d = backlog_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "done.md").write_text("""---
goal: Done
files: a.py
done: true
---
""", encoding="utf-8")
    (d / "invalid.md").write_text("""---
files: b.py
---
""", encoding="utf-8")
    spec = select_next(tmp_path)
    assert spec is None


def test_validation_report_returns_errors(tmp_path):
    """validation_report returns (slug, errors) tuples for invalid specs."""
    from chimera.core.backlog import validation_report, backlog_dir
    d = backlog_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "bad.md").write_text("""---
files: a.py
---
""", encoding="utf-8")
    report = validation_report(tmp_path)
    assert len(report) == 1
    slug, errors = report[0]
    assert slug == "bad"
    assert errors == ("missing required `goal`",)


def test_parse_spec_repo_without_verify_cmd_is_invalid(tmp_path):
    """A foreign-repo spec without verify_cmd is rejected."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Do the thing
files: a.py
repo: owner/name
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert not spec.valid
    assert "`repo` is set but `verify_cmd` is missing (a foreign repo needs its own gate)" in spec.errors


def test_slug_property(tmp_path):
    """BacklogSpec.slug is the filename stem without extension."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "my-task-slug.md"
    p.write_text("""---
goal: A task
files: a.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert spec.slug == "my-task-slug"


def test_parse_spec_goal_and_files(tmp_path):
    """parse_spec correctly extracts goal and files."""
    from chimera.core.backlog import parse_spec
    p = tmp_path / "task.md"
    p.write_text("""---
goal: Fix the bug
files: src/a.py src/b.py
---
""", encoding="utf-8")
    spec = parse_spec(p)
    assert spec.goal == "Fix the bug"
    assert spec.files == ("src/a.py", "src/b.py")
    assert spec.valid
