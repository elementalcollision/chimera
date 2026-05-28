"""Tests for the pre-commit scope check (ADR 0146).

Closes the v35 attempt #3 confabulation gap: agent committed
"I didn't do the work" then ~2 minutes later committed a fabricated
diagnosis. Engine guards saw it but couldn't undo the commit. The
scope check refuses at commit-time.

Test plan (written before implementation):

1. Parser extracts the section body under `## READY-FOR-REMEDIATION`.
2. Parser recognizes "no code change" and a backtick-quoted file
   allowlist.
3. Classifier refuses an R2-shaped diff when recommendation says R1
   (no code change).
4. Classifier refuses paths outside the recommended allowlist.
5. Classifier allows docs/research even when recommendation says
   "no code change".
6. Conservative refusal: ambiguous section → warn, never refuse.
7. The override env var lets the commit through with a logged event.
8. End-to-end fake repo: R1 design note + R2-shaped staged diff →
   refusal raised.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from chimera.core.scope_check import (
    Recommendation,
    ScopeCheckRefusal,
    _OVERRIDE_ENV,
    check_commit_scope,
    classify_diff,
    evaluate_commit_scope,
    extract_ready_for_remediation,
    find_active_design_note,
    parse_recommendation,
    record_event,
    resolve_repo_root,
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_extract_section_returns_body_until_next_heading():
    text = (
        "# Title\n"
        "\n"
        "Some prose.\n"
        "\n"
        "## READY-FOR-REMEDIATION\n"
        "\n"
        "R1 — no code change. Reopen with a fresh chip.\n"
        "\n"
        "## Appendix\n"
        "more stuff\n"
    )
    body = extract_ready_for_remediation(text)
    assert body is not None
    assert "R1" in body
    assert "Appendix" not in body
    assert "more stuff" not in body


def test_extract_section_runs_to_eof_when_no_following_heading():
    text = "intro\n\n## READY-FOR-REMEDIATION\n\nR1 — pick this.\n"
    body = extract_ready_for_remediation(text)
    assert body == "R1 — pick this."


def test_extract_section_returns_none_when_missing():
    assert extract_ready_for_remediation("# foo\n\nno section here\n") is None


def test_extract_section_empty_body_is_distinguished_from_missing():
    text = "## READY-FOR-REMEDIATION\n"
    body = extract_ready_for_remediation(text)
    assert body == ""  # empty != None


def test_parse_recommendation_extracts_r_tag():
    rec = parse_recommendation("R1 — no code change. Reopen later.")
    assert rec.r_tag == "R1"
    assert rec.no_code_change is True


def test_parse_recommendation_extracts_path_allowlist():
    rec = parse_recommendation(
        "R2 — touch `chimera/evals/locomo.py` and "
        "`tests/test_locomo.py` only."
    )
    assert rec.r_tag == "R2"
    assert "chimera/evals/locomo.py" in rec.allowed_paths
    assert "tests/test_locomo.py" in rec.allowed_paths
    assert rec.no_code_change is False


def test_parse_recommendation_ambiguous_when_empty():
    rec = parse_recommendation("")
    assert rec.is_ambiguous is True


def test_parse_recommendation_ambiguous_when_just_prose():
    rec = parse_recommendation("TBD. Need more data before deciding.")
    assert rec.is_ambiguous is True


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------


def _rec(
    *,
    r_tag: str | None = None,
    paths: tuple[str, ...] = (),
    no_code: bool = False,
) -> Recommendation:
    return Recommendation(
        section_text="",
        r_tag=r_tag,
        allowed_paths=paths,
        no_code_change=no_code,
    )


def test_classify_refuses_code_change_when_recommendation_is_no_code():
    rec = _rec(r_tag="R1", no_code=True)
    verdict, offenders = classify_diff(
        ("chimera/evals/locomo.py",), rec
    )
    assert verdict == "refuse"
    assert offenders == ("chimera/evals/locomo.py",)


def test_classify_allows_docs_when_recommendation_is_no_code():
    rec = _rec(r_tag="R1", no_code=True)
    verdict, offenders = classify_diff(
        ("docs/adr/0146-pre-commit-scope-check.md", "mind/research/foo.md"),
        rec,
    )
    assert verdict == "allow"
    assert offenders == ()


def test_classify_refuses_paths_outside_allowlist():
    rec = _rec(r_tag="R2", paths=("chimera/evals/locomo.py",))
    verdict, offenders = classify_diff(
        ("chimera/evals/locomo.py", "chimera/evals/hybrid_retrieval.py"),
        rec,
    )
    assert verdict == "refuse"
    assert offenders == ("chimera/evals/hybrid_retrieval.py",)


def test_classify_allows_paths_within_allowlist():
    rec = _rec(r_tag="R2", paths=("chimera/evals/locomo.py",))
    verdict, offenders = classify_diff(
        ("chimera/evals/locomo.py",), rec
    )
    assert verdict == "allow"


def test_classify_ambiguous_is_warn_only():
    rec = _rec()  # nothing actionable
    verdict, _ = classify_diff(
        ("chimera/core/loop.py",), rec
    )
    assert verdict == "warn"


def test_classify_r_tag_alone_is_warn_only():
    # R-tag with no allowlist and no no-code signal — cannot safely
    # refuse on R-tag alone.
    rec = _rec(r_tag="R3")
    verdict, _ = classify_diff(
        ("chimera/core/loop.py",), rec
    )
    assert verdict == "warn"


def test_classify_empty_diff_is_allow():
    rec = _rec(r_tag="R1", no_code=True)
    verdict, _ = classify_diff((), rec)
    assert verdict == "allow"


# ---------------------------------------------------------------------------
# End-to-end (fake on-disk repo with a real git index)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _write_design_note(repo: Path, body: str, name: str = "chip-design.md") -> Path:
    research = repo / "mind" / "research"
    research.mkdir(parents=True, exist_ok=True)
    note = research / name
    note.write_text(body, encoding="utf-8")
    return note


def test_find_active_design_note_returns_latest(tmp_path):
    repo = _init_repo(tmp_path)
    a = _write_design_note(repo, "## READY-FOR-REMEDIATION\nR1\n", "a-design.md")
    b = _write_design_note(repo, "## READY-FOR-REMEDIATION\nR2\n", "b-design.md")
    # Touch b after a to ensure deterministic mtime ordering.
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    found = find_active_design_note(repo)
    assert found is not None
    assert found.name == "b-design.md"


def test_find_active_design_note_none_when_dir_missing(tmp_path):
    repo = _init_repo(tmp_path)
    assert find_active_design_note(repo) is None


# ---------------------------------------------------------------------------
# Branch-prefix matching (v36-postmortem follow-up C, PR #117)
# ---------------------------------------------------------------------------


def test_find_active_design_note_matches_branch_prefix(tmp_path):
    """When HEAD is on a chip branch like ``chimera-soak/v36-...``, prefer the
    ``v36-*-design.md`` note even if a ``v34-*-design.md`` has a newer mtime.

    Regression test for the v36 micro-soak postmortem (PR #117): the
    previous "latest by mtime" heuristic selected v34's note during the
    v36 soak. The reasoning trace looked correct only because
    ``mind/research/*`` is auto-allowed independently.
    """
    repo = _init_repo(tmp_path)
    v34 = _write_design_note(
        repo,
        "## READY-FOR-REMEDIATION\nR1 — no code change.\n",
        "v34-preference-dialectic-design.md",
    )
    v36 = _write_design_note(
        repo,
        "## READY-FOR-REMEDIATION\nR1 — no code change.\n",
        "v36-temporal-regression-design.md",
    )
    # v34 is newer by mtime so the legacy heuristic would pick it.
    os.utime(v36, (1, 1))
    os.utime(v34, (2, 2))
    _git(repo, "checkout", "-q", "-b", "chimera-soak/v36-2026-05-28-1537")

    found = find_active_design_note(repo)
    assert found is not None
    assert found.name == "v36-temporal-regression-design.md"
    assert found.resolve() == v36.resolve()


def test_find_active_design_note_falls_back_to_mtime_when_no_prefix_match(
    tmp_path,
):
    """On ``main`` (no chip prefix) the mtime fallback must be preserved."""
    repo = _init_repo(tmp_path)
    a = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR1\n", "a-design.md"
    )
    b = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR2\n", "b-design.md"
    )
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    # _init_repo already left us on ``main``.
    found = find_active_design_note(repo)
    assert found is not None
    assert found.name == "b-design.md"


def test_find_active_design_note_detached_head_falls_back(tmp_path):
    """Detached HEAD must not raise; falls back to mtime ordering."""
    repo = _init_repo(tmp_path)
    a = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR1\n", "a-design.md"
    )
    b = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR2\n", "b-design.md"
    )
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    # Detach HEAD at the seed commit.
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "--detach", head_sha)

    found = find_active_design_note(repo)
    assert found is not None
    assert found.name == "b-design.md"


def test_find_active_design_note_branch_without_slash_falls_back(tmp_path):
    """A branch name with no ``/`` separator falls back cleanly."""
    repo = _init_repo(tmp_path)
    a = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR1\n", "a-design.md"
    )
    b = _write_design_note(
        repo, "## READY-FOR-REMEDIATION\nR2\n", "b-design.md"
    )
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    _git(repo, "checkout", "-q", "-b", "feature-foo")

    found = find_active_design_note(repo)
    assert found is not None
    assert found.name == "b-design.md"


def test_find_active_design_note_no_design_notes_returns_none(tmp_path):
    """Empty ``mind/research/`` returns None regardless of branch."""
    repo = _init_repo(tmp_path)
    (repo / "mind" / "research").mkdir(parents=True, exist_ok=True)
    _git(repo, "checkout", "-q", "-b", "chimera-soak/v99-2026-05-28-0000")
    assert find_active_design_note(repo) is None


def test_evaluate_warns_when_no_design_note(tmp_path):
    repo = _init_repo(tmp_path)
    result = evaluate_commit_scope(repo)
    assert result.verdict == "warn"
    assert "no design note" in result.reason


def test_evaluate_warns_when_section_missing(tmp_path):
    repo = _init_repo(tmp_path)
    _write_design_note(repo, "# Title\n\nno sentinel here\n")
    result = evaluate_commit_scope(repo)
    assert result.verdict == "warn"
    assert "READY-FOR-REMEDIATION" in result.reason


def test_evaluate_refuses_r1_design_with_r2_shaped_diff(tmp_path):
    """The v35 attempt #3 failure pattern, locked in as a regression test.

    Phase 1 design note's `## READY-FOR-REMEDIATION` says
    "R1 — no code change". The agent then stages an R2-shaped diff
    that touches `chimera/evals/locomo.py`. The check must refuse.
    """
    repo = _init_repo(tmp_path)
    _write_design_note(
        repo,
        "# v35 LoCoMo temporal-regression design\n\n"
        "## READY-FOR-REMEDIATION\n\n"
        "R1 — no code change. Reopen with a fresh chip after a "
        "real classification table exists.\n",
    )
    # Stage an R2-shaped change.
    evals = repo / "chimera" / "evals"
    evals.mkdir(parents=True, exist_ok=True)
    (evals / "locomo.py").write_text("# fabricated change\n")
    _git(repo, "add", "chimera/evals/locomo.py")

    result = evaluate_commit_scope(repo)
    assert result.verdict == "refuse"
    assert "chimera/evals/locomo.py" in result.offending_paths
    assert result.recommendation is not None
    assert result.recommendation.no_code_change is True


def test_check_commit_scope_raises_on_refusal(tmp_path):
    repo = _init_repo(tmp_path)
    _write_design_note(
        repo,
        "## READY-FOR-REMEDIATION\nR1 — no code change.\n",
    )
    (repo / "chimera").mkdir()
    (repo / "chimera" / "x.py").write_text("y = 1\n")
    _git(repo, "add", "chimera/x.py")

    with pytest.raises(ScopeCheckRefusal) as exc_info:
        check_commit_scope(repo)
    assert exc_info.value.result.verdict == "refuse"
    assert "chimera/x.py" in exc_info.value.result.offending_paths


def test_check_commit_scope_override_allows_with_logged_event(
    tmp_path, monkeypatch
):
    repo = _init_repo(tmp_path)
    _write_design_note(
        repo,
        "## READY-FOR-REMEDIATION\nR1 — no code change.\n",
    )
    (repo / "chimera").mkdir()
    (repo / "chimera" / "x.py").write_text("y = 1\n")
    _git(repo, "add", "chimera/x.py")

    state_dir = tmp_path / "state"
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv(_OVERRIDE_ENV, "1")

    result = check_commit_scope(repo)
    assert result.verdict == "refuse"
    assert result.override_used is True
    assert "overridden" in result.reason

    events = (state_dir / "scope_check_events.jsonl").read_text().splitlines()
    assert len(events) == 1
    rec = json.loads(events[0])
    assert rec["event"] == "scope_check_override"
    assert rec["override_used"] is True
    assert "chimera/x.py" in rec["offending_paths"]


def test_record_event_appends_jsonl(tmp_path, monkeypatch):
    from chimera.core.scope_check import ScopeCheckResult

    state_dir = tmp_path / "s"
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    record_event(
        ScopeCheckResult(
            verdict="refuse",
            reason="test",
            staged_paths=("x.py",),
            offending_paths=("x.py",),
        )
    )
    lines = (state_dir / "scope_check_events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "scope_check_refusal"
    assert rec["offending_paths"] == ["x.py"]


def test_resolve_repo_root_returns_toplevel(tmp_path):
    repo = _init_repo(tmp_path)
    sub = repo / "deep" / "nested"
    sub.mkdir(parents=True)
    assert resolve_repo_root(sub).resolve() == repo.resolve()


def test_resolve_repo_root_returns_input_on_non_git(tmp_path):
    assert resolve_repo_root(tmp_path).resolve() == tmp_path.resolve()
