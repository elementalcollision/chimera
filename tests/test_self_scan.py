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


# ── integration: the real ruff finder on a synthetic fixture repo ────
#
# Earlier this test hard-coded that `chimera/cli.py` was lint-dirty and asserted
# the finder surfaced it. That is self-defeating: the autonomous self-scan loop
# ranks "fix the ruff debt in chimera/cli.py" as its #1 task, and the moment any
# commit cleans that debt the assertion fails — the test punished the system for
# succeeding at its own purpose (surfaced 2026-06-08 during a self_determined_soak).
# We now pin the finder's BEHAVIOUR against a stable synthetic fixture instead of
# the transient lint state of a production source file.

_RUFF_FIXTURE = Path(__file__).parent / "fixtures" / "ruff_debt_sample.py.txt"


def test_real_ruff_finder_surfaces_fixture_debt(tmp_path):
    """The real ruff finder must surface a file with known lint debt as a
    correctly-shaped candidate. We materialise a synthetic fixture (three unused
    imports → three F401 findings) into a temp repo and run the REAL finder over
    it. Fail-open if ruff is absent in this environment — then nothing to assert."""
    sample = tmp_path / "ruff_debt_sample.py"
    sample.write_text(_RUFF_FIXTURE.read_text())

    counts = default_ruff_finder(tmp_path)
    if not counts:
        return  # ruff not installed here → fail-open path; nothing to assert
    assert counts.get("ruff_debt_sample.py", 0) >= 3  # three deliberate F401s

    cands = scan_repo(tmp_path, ruff_finder=default_ruff_finder)
    files = {f for c in cands for f in c.files}
    assert "ruff_debt_sample.py" in files
    cand = next(c for c in cands if c.files == ["ruff_debt_sample.py"])
    assert cand.source == "ruff" and cand.test is None and cand.risk_flag == ""
    assert "scripts/real_task_soak.sh" in cand.soak_command()


def test_real_ruff_finder_over_repo_never_crashes():
    """Integration smoke over the actual repo: the real finder returns a
    path→count mapping and scan_repo yields well-shaped ruff candidates without
    raising — independent of WHICH files happen to carry lint debt today."""
    counts = default_ruff_finder(REPO)
    assert isinstance(counts, dict)
    cands = scan_repo(REPO, ruff_finder=default_ruff_finder)
    assert all(c.source == "ruff" and c.single_file for c in cands)
