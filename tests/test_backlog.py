"""CRAWL backlog spec parsing + selection (ADR 0182, phase 1)."""

from __future__ import annotations

from pathlib import Path

from chimera.core.backlog import (
    backlog_dir,
    list_specs,
    parse_spec,
    select_next,
    validation_report,
)


def _write(d: Path, name: str, text: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


_GOOD = """---
goal: Fix the deprecated utcnow call
files: tests/test_x.py chimera/foo.py
test: tests/test_x.py
base: main
---
Replace utcnow() with timezone-aware now(UTC). Acceptance: -W error passes.
"""


def test_parse_valid_spec(tmp_path):
    p = _write(tmp_path, "task.md", _GOOD)
    s = parse_spec(p)
    assert s.valid
    assert s.goal == "Fix the deprecated utcnow call"
    assert s.files == ("tests/test_x.py", "chimera/foo.py")
    assert s.test == "tests/test_x.py"
    assert s.base == "main"
    assert s.slug == "task"
    assert "Replace utcnow" in s.body


def test_task_env_maps_to_soak_vars(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", _GOOD))
    env = s.task_env()
    assert env["TASK_GOAL"] == "Fix the deprecated utcnow call"
    assert env["TASK_FILES"] == "tests/test_x.py chimera/foo.py"
    assert env["TASK_TEST"] == "tests/test_x.py"
    assert env["TASK_BASE"] == "main"


def test_files_as_yaml_list(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", """---
goal: g
files:
  - a.py
  - b.py
---
body
"""))
    assert s.valid
    assert s.files == ("a.py", "b.py")


def test_base_defaults_to_main_and_test_optional(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", """---
goal: g
files: a.py
---
"""))
    assert s.valid
    assert s.base == "main"
    assert s.test is None
    assert "TASK_TEST" not in s.task_env()


def test_missing_goal_is_invalid(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", "---\nfiles: a.py\n---\n"))
    assert not s.valid
    assert any("goal" in e for e in s.errors)


def test_missing_files_is_invalid(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", "---\ngoal: g\n---\n"))
    assert not s.valid
    assert any("files" in e for e in s.errors)


def test_no_frontmatter_is_invalid(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", "just a plain note, no frontmatter\n"))
    assert not s.valid
    assert any("frontmatter" in e for e in s.errors)


def test_malformed_yaml_is_invalid_not_raise(tmp_path):
    s = parse_spec(_write(tmp_path, "t.md", "---\ngoal: [unclosed\n---\n"))
    assert not s.valid
    assert any("YAML" in e for e in s.errors)


def test_done_marker_excludes_from_selection(tmp_path):
    mind = tmp_path / "mind"
    _write(backlog_dir(mind), "done.md", """---
goal: already done
files: a.py
done: true
---
""")
    assert select_next(mind) is None


def test_select_next_is_oldest_valid_unclaimed(tmp_path):
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "01-first.md", "---\ngoal: first\nfiles: a.py\n---\n")
    _write(d, "02-second.md", "---\ngoal: second\nfiles: b.py\n---\n")
    # Oldest by name wins.
    assert select_next(mind).slug == "01-first"
    # Claiming the first advances to the second.
    nxt = select_next(mind, claimed_slugs=frozenset({"01-first"}))
    assert nxt.slug == "02-second"


def test_select_next_skips_invalid_specs(tmp_path):
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "01-bad.md", "---\nfiles: a.py\n---\n")        # no goal
    _write(d, "02-good.md", "---\ngoal: g\nfiles: b.py\n---\n")
    assert select_next(mind).slug == "02-good"


def test_validation_report_surfaces_invalid(tmp_path):
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "bad.md", "---\nfiles: a.py\n---\n")
    _write(d, "good.md", "---\ngoal: g\nfiles: b.py\n---\n")
    report = validation_report(mind)
    assert len(report) == 1
    assert report[0][0] == "bad"
    assert any("goal" in e for e in report[0][1])


def test_empty_or_missing_backlog_dir(tmp_path):
    assert list_specs(tmp_path / "mind") == []
    assert select_next(tmp_path / "mind") is None


def test_readme_and_dotfiles_are_not_specs(tmp_path):
    mind = tmp_path / "mind"
    d = backlog_dir(mind)
    _write(d, "README.md", "# Backlog docs\nNo frontmatter here.\n")
    _write(d, ".draft.md", "---\ngoal: wip\nfiles: a.py\n---\n")
    _write(d, "01-real.md", "---\ngoal: real\nfiles: a.py\n---\n")
    slugs = [s.slug for s in list_specs(mind)]
    assert slugs == ["01-real"]
    assert validation_report(mind) == []  # README is not flagged INVALID


# ── picker gate-visibility exit-code mapping (ADR 0182) ─────


def _spec(tmp_path):
    return parse_spec(_write(tmp_path, "t.md", _GOOD))


def test_gate_check_visible_returns_0(tmp_path, monkeypatch):
    """Gate RED on base → gate-visible → proceed (0)."""
    from chimera.cli_cmds import backlog as bl
    from chimera.core import repo_verify as rv

    red = rv.VerificationReport(checks=[])  # .ok is False (no checks)
    monkeypatch.setattr(rv, "verify_at_ref", lambda *a, **k: red)
    assert bl._check_gate_visibility(_spec(tmp_path)) == 0


def test_gate_check_invisible_returns_3(tmp_path, monkeypatch, capsys):
    """Gate already GREEN on base → gate-invisible → reject (3)."""
    from chimera.cli_cmds import backlog as bl
    from chimera.core import repo_verify as rv

    green = rv.VerificationReport(checks=[rv.CheckResult("x", True)])  # .ok True
    monkeypatch.setattr(rv, "verify_at_ref", lambda *a, **k: green)
    assert bl._check_gate_visibility(_spec(tmp_path)) == 3
    assert "GATE-INVISIBLE" in capsys.readouterr().out


def test_gate_check_base_error_returns_4(tmp_path, monkeypatch):
    """Base ref could not be evaluated → 4."""
    from chimera.cli_cmds import backlog as bl
    from chimera.core import repo_verify as rv

    monkeypatch.setattr(rv, "verify_at_ref", lambda *a, **k: None)
    assert bl._check_gate_visibility(_spec(tmp_path)) == 4
