"""Self-origination chip 1 (ADR 0161): scan_repo emits ranked, behaviour-neutral
candidate task triples. PROPOSAL-ONLY — it launches nothing.

Finders are injectable so these stay deterministic (no real ruff/pytest), with
one integration test that runs the real ruff finder against this repo's known
`chimera/cli.py` lint debt.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.self_scan import (
    TaskCandidate,
    default_ruff_finder,
    rank,
    scan_repo,
)

REPO = Path(__file__).resolve().parents[1]


# ── the acceptance criterion: both sources, ranked, single-file ──────


def test_scan_emits_both_sources_as_single_file_triples():
    ruff = lambda root: {"chimera/x.py": 3}                       # noqa: E731
    mut = lambda root: [("tests/test_y.py", "chimera/y.py", 2)]   # noqa: E731
    cands = scan_repo(REPO, ruff_finder=ruff, mutation_finder=mut)
    assert len(cands) == 2
    assert all(c.single_file for c in cands)
    by_src = {c.source: c for c in cands}
    assert by_src["ruff"].files == ["chimera/x.py"]
    assert by_src["ruff"].test is None
    # mutation candidate's CHANGE is to the TEST file (behaviour-neutral)
    assert by_src["mutation"].files == ["tests/test_y.py"]
    assert by_src["mutation"].test == "tests/test_y.py"
    assert all(c.risk_flag == "" for c in cands)  # both safe


def test_test_only_mutation_ranks_above_source_editing_ruff():
    ruff = lambda root: {"chimera/x.py": 9}                       # noqa: E731
    mut = lambda root: [("tests/test_y.py", "chimera/y.py", 1)]   # noqa: E731
    cands = scan_repo(REPO, ruff_finder=ruff, mutation_finder=mut)
    assert cands[0].source == "mutation"  # test-only is safest → ranked first


def test_clean_repo_yields_no_candidates():
    empty = lambda root: {}        # noqa: E731
    empty_m = lambda root: []      # noqa: E731
    assert scan_repo(REPO, ruff_finder=empty, mutation_finder=empty_m) == []


def test_mutation_finder_opt_in_default_skips():
    # default mutation_finder is None → only ruff runs (here a no-op fake)
    assert scan_repo(REPO, ruff_finder=lambda r: {}) == []


def test_zero_count_findings_are_dropped():
    ruff = lambda root: {"chimera/x.py": 0}        # noqa: E731
    assert scan_repo(REPO, ruff_finder=ruff) == []


# ── robustness: never raise ──────────────────────────────────────────


def test_finder_exception_does_not_crash_scan():
    def boom(root):
        raise RuntimeError("finder bug")
    # ruff finder throws → fail-open to [] (mutation still off)
    assert scan_repo(REPO, ruff_finder=boom) == []


def test_soak_command_is_copy_pasteable():
    c = TaskCandidate(goal="fix the 2 ruff lint finding(s) in chimera/x.py",
                      files=["chimera/x.py"], test=None, source="ruff", score=0.9)
    cmd = c.soak_command(base="main")
    assert 'TASK_GOAL="fix the 2 ruff lint finding(s) in chimera/x.py"' in cmd
    assert 'TASK_FILES="chimera/x.py"' in cmd
    assert "TASK_TEST" not in cmd  # lint-only candidate
    assert cmd.endswith("bash scripts/real_task_soak.sh")
    c2 = TaskCandidate(goal="g", files=["tests/test_y.py"], test="tests/test_y.py",
                       source="mutation", score=1.0)
    assert 'TASK_TEST="tests/test_y.py"' in c2.soak_command()


def test_rank_is_deterministic_and_stable():
    cs = [
        TaskCandidate("a", ["z.py"], None, "ruff", 0.9),
        TaskCandidate("b", ["a.py"], None, "ruff", 0.9),
        TaskCandidate("c", ["t.py"], "t.py", "mutation", 1.0),
    ]
    out = [c.files[0] for c in rank(cs)]
    assert out == ["t.py", "a.py", "z.py"]  # score desc, then file name


# ── integration: the real ruff finder on this repo ──────────────────


def test_real_ruff_finder_surfaces_cli_debt():
    """chimera/cli.py carries known pre-existing ruff debt; the real finder must
    surface it as a candidate (the design's anchor case). Fail-open if ruff is
    absent in this environment — then we assert only that it did not crash."""
    counts = default_ruff_finder(REPO)
    if not counts:
        return  # ruff not installed here → fail-open path; nothing to assert
    cands = scan_repo(REPO, ruff_finder=default_ruff_finder)
    files = {f for c in cands for f in c.files}
    assert "chimera/cli.py" in files
    cli = next(c for c in cands if c.files == ["chimera/cli.py"])
    assert cli.source == "ruff" and cli.test is None and cli.risk_flag == ""
    assert "scripts/real_task_soak.sh" in cli.soak_command()
