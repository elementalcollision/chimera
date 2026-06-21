"""WALK — GitHub issue → backlog spec ingestion (ADR 0182 phase 2)."""

from __future__ import annotations

from chimera.core.backlog import backlog_dir, list_specs, select_next
from chimera.core.issue_backlog import (
    ingest_issues,
    issue_to_spec_markdown,
    spec_block,
)

_REPO = "elementalcollision/chimera"

_BODY_WITH_SPEC = """\
Some narrative describing the bug.

```yaml
goal: Fix the frobnicator off-by-one
files: chimera/foo.py tests/test_foo.py
test: tests/test_foo.py
base: main
```

More context below.
"""


def _issue(number=7, title="Frobnicator off-by-one", body=_BODY_WITH_SPEC):
    return {"number": number, "title": title, "body": body}


# ── spec_block ──────────────────────────────────────────────


def test_spec_block_extracts_yaml():
    b = spec_block(_BODY_WITH_SPEC)
    assert b["goal"] == "Fix the frobnicator off-by-one"
    assert b["files"] == "chimera/foo.py tests/test_foo.py"


def test_spec_block_none_when_absent():
    assert spec_block("just prose, no fenced block") is None
    assert spec_block("") is None
    assert spec_block(None) is None


def test_spec_block_malformed_yaml_is_none():
    assert spec_block("```yaml\ngoal: [unclosed\n```") is None


def test_spec_block_accepts_spec_fence():
    assert spec_block("```spec\ngoal: g\nfiles: a.py\n```")["files"] == "a.py"


# ── issue_to_spec_markdown ──────────────────────────────────


def test_issue_renders_valid_spec_markdown(tmp_path):
    md = issue_to_spec_markdown(_issue(), _REPO)
    assert md is not None
    # Round-trips through the normal spec parser.
    p = tmp_path / "issue-7.md"
    p.write_text(md)
    from chimera.core.backlog import parse_spec
    s = parse_spec(p)
    assert s.valid
    assert s.goal == "Fix the frobnicator off-by-one"
    assert s.files == ("chimera/foo.py", "tests/test_foo.py")
    assert s.test == "tests/test_foo.py"
    assert s.issue == f"{_REPO}#7"


def test_issue_without_block_returns_none():
    assert issue_to_spec_markdown(_issue(body="no spec here"), _REPO) is None


def test_issue_goal_falls_back_to_title():
    body = "```yaml\nfiles: a.py\n```"
    md = issue_to_spec_markdown(_issue(title="Use the title", body=body), _REPO)
    assert "goal: Use the title" in md


def test_block_without_files_is_rejected():
    # files is required for a gate-visible spec.
    body = "```yaml\ngoal: vague feature, no files\n```"
    assert issue_to_spec_markdown(_issue(body=body), _REPO) is None


# ── ingest_issues (injected, no gh) ─────────────────────────


def test_ingest_writes_specs_and_skips_unspecced(tmp_path):
    mind = tmp_path / "mind"
    issues = [
        _issue(number=10, title="Real task"),
        _issue(number=11, title="Vague request", body="no block"),
    ]
    results = ingest_issues(_REPO, mind_dir=mind, issues=issues)
    assert len(results) == 2
    written = [r for r in results if r.written is not None]
    assert len(written) == 1
    assert written[0].number == 10
    # The ingested spec is now selectable by the existing picker.
    specs = list_specs(mind)
    assert len(specs) == 1
    assert specs[0].issue == f"{_REPO}#10"
    assert select_next(mind).issue == f"{_REPO}#10"


def test_ingest_filename_keyed_on_repo_and_number(tmp_path):
    # MF-3: the spec filename is keyed on (repo, number) — NOT the title — so a
    # re-titled issue can't mint a duplicate and two repos can't collide.
    mind = tmp_path / "mind"
    ingest_issues(_REPO, mind_dir=mind, issues=[_issue(number=42, title="X Y")])
    names = [p.name for p in backlog_dir(mind).glob("*.md")]
    assert names == ["issue-elementalcollision-chimera-42.md"]


def test_ingest_empty_list(tmp_path):
    assert ingest_issues(_REPO, mind_dir=tmp_path / "mind", issues=[]) == []
