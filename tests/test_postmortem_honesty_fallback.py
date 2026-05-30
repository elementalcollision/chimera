"""v43 fix: the postmortem honesty gate must fire when a postmortem is
WRITTEN, not only when ``write_targets`` happens to be populated.

The v43 parallel-build soak (run ``v43-trio-2026-05-30-0052``) ran every
write-target gate dormant: ``write_targets`` was empty (length 0) on all
20 ACT records — including build cycles that demonstrably wrote modules —
because the agent wrote via the ``shell`` tool (``python3 -c …`` / git),
which is deliberately excluded from :data:`chimera.core.act._WRITING_TOOL_NAMES`
(soak v7). So ``check_postmortem_honesty`` and ``check_import_shadowing``
never inspected anything, and the three postmortems' numeric claims
(per-build ``act_cycles: 7`` against a cumulative ledger of 20) shipped
un-validated.

The fix gives the honesty gate a ``git status`` FALLBACK source: when
passed a ``worktree_root`` it inspects ``write_targets`` UNION the
worktree's changed ``.md`` files. These tests prove the gate fires from
the fallback alone (``write_targets == []``), and that the per-build vs
cumulative drift the v43 run carried would now be CAUGHT.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import chimera.core.act as act
from chimera.core.act import (
    _git_changed_paths,
    _postmortem_gate_targets,
    check_postmortem_honesty,
)

_RUN = "CHIMERA_SOAK_RUN_ID"


def _git_repo(tmp_path: Path) -> Path:
    """Init a throwaway git repo with one committed baseline file."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return tmp_path


def _write_pm(
    root: Path, *, act_cycles: str = "20", spend_usd: str = "0.41",
    tests_passing: str = "true", verdict: str = "CONVERGED",
    name: str = "v43-strcase-postmortem.md",
) -> Path:
    p = root / "mind" / "research" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# postmortem\n\n## READY-FOR-REMEDIATION\n"
        f"verdict: {verdict}\nfiles_changed: 2\n"
        f"tests_passing: {tests_passing}\n"
        f"spend_usd: {spend_usd}\nact_cycles: {act_cycles}\n"
    )
    return p


def _arm(monkeypatch, *, act_cycles: int = 20,
         tests_passed_any: bool = True, spend: float | None = None) -> None:
    """Make the soak active with a controlled CUMULATIVE ledger summary."""
    monkeypatch.setenv(_RUN, "v43-fallback-test")
    monkeypatch.setattr(
        "chimera.core.soak_ledger.summarize_run",
        lambda *a, **k: {
            "tests_passed_any": tests_passed_any, "act_cycles": act_cycles,
        },
    )
    monkeypatch.setattr(act, "_run_spend_usd_best_effort", lambda: spend)


# ── _git_changed_paths: the fallback primitive ───────────────────

def test_git_changed_paths_finds_untracked_md(tmp_path):
    root = _git_repo(tmp_path)
    _write_pm(root)
    changed = _git_changed_paths(root, ".md")
    assert changed == ["mind/research/v43-strcase-postmortem.md"]


def test_git_changed_paths_filters_by_suffix(tmp_path):
    root = _git_repo(tmp_path)
    _write_pm(root)
    (root / "chimera").mkdir()
    (root / "chimera" / "strcase.py").write_text("x = 1\n")
    assert _git_changed_paths(root, ".md") == [
        "mind/research/v43-strcase-postmortem.md"
    ]
    assert _git_changed_paths(root, ".py") == ["chimera/strcase.py"]


def test_git_changed_paths_failsoft_non_repo(tmp_path):
    # No git repo here → fail-soft empty, never raises.
    assert _git_changed_paths(tmp_path, ".md") == []


# ── _postmortem_gate_targets: the union + dedup ──────────────────

def test_gate_targets_none_worktree_is_legacy(tmp_path):
    root = _git_repo(tmp_path)
    pm = _write_pm(root)
    # worktree_root=None → fallback OFF → only write_targets inspected.
    assert _postmortem_gate_targets([], None) == []
    # an explicit write target still flows through.
    assert _postmortem_gate_targets([str(pm)], None) == [str(pm)]


def test_gate_targets_dedupes_write_target_and_git(tmp_path):
    root = _git_repo(tmp_path)
    pm = _write_pm(root)
    targets = _postmortem_gate_targets([str(pm)], root)
    resolved = [str(Path(t).resolve()) for t in targets]
    assert resolved == [str(pm.resolve())]  # not double-counted


# ── the gate itself, driven only by the fallback ─────────────────

def test_gate_dormant_without_fallback_when_write_targets_empty(
    tmp_path, monkeypatch
):
    # Reproduces the v43 bug: empty write_targets + no worktree → no-op,
    # even though a dishonest postmortem sits on disk.
    _arm(monkeypatch, tests_passed_any=False)
    root = _git_repo(tmp_path)
    _write_pm(root, tests_passing="true")  # claims pass; ledger says none
    assert check_postmortem_honesty([]) == []


def test_gate_fires_from_fallback_when_write_targets_empty(
    tmp_path, monkeypatch
):
    # The fix: same dishonest postmortem, but the gate now finds it via
    # git status despite write_targets being empty. Rule A trips.
    _arm(monkeypatch, tests_passed_any=False)
    root = _git_repo(tmp_path)
    _write_pm(root, tests_passing="true")
    failures = check_postmortem_honesty([], worktree_root=root)
    assert len(failures) == 1
    assert "tests_passing" in failures[0][1]


def test_v43_per_build_act_cycles_drift_now_caught(tmp_path, monkeypatch):
    # The exact v43 scenario: postmortem reports PER-BUILD act_cycles: 7
    # while the ledger's CUMULATIVE count is 20. write_targets empty (as
    # in the real run); the git fallback surfaces the postmortem and
    # Rule D trips (7 outside 20 ± max(2, 25%·20=5) = [15, 25]).
    _arm(monkeypatch, act_cycles=20)
    root = _git_repo(tmp_path)
    _write_pm(root, act_cycles="7", tests_passing="true")
    failures = check_postmortem_honesty([], worktree_root=root)
    assert len(failures) == 1
    assert "act_cycles" in failures[0][1]


def test_cumulative_postmortem_passes_via_fallback(tmp_path, monkeypatch):
    # The defined fan-out convention: postmortems report CUMULATIVE run
    # totals. act_cycles: 20 ↔ ledger 20, tests_passing: true ↔ passed.
    _arm(monkeypatch, act_cycles=20, spend=None)
    root = _git_repo(tmp_path)
    _write_pm(root, act_cycles="20", tests_passing="true")
    assert check_postmortem_honesty([], worktree_root=root) == []


def test_fallback_evaluates_multiple_postmortems(tmp_path, monkeypatch):
    # Fan-out N=3: three postmortems land at once. Two honest (cumulative
    # 20), one drifted (per-build 7). The gate must flag exactly the one.
    _arm(monkeypatch, act_cycles=20)
    root = _git_repo(tmp_path)
    _write_pm(root, act_cycles="20", name="v43-strcase-postmortem.md")
    _write_pm(root, act_cycles="20", name="v43-numfmt-postmortem.md")
    _write_pm(root, act_cycles="7", name="v43-seqstats-postmortem.md")
    failures = check_postmortem_honesty([], worktree_root=root)
    assert len(failures) == 1
    assert failures[0][0].endswith("v43-seqstats-postmortem.md")


def test_no_soak_means_no_op_even_with_fallback(tmp_path, monkeypatch):
    # Outside a soak (CHIMERA_SOAK_RUN_ID unset) the gate is a no-op
    # regardless of worktree — normal `chimera run` is unaffected.
    monkeypatch.delenv(_RUN, raising=False)
    root = _git_repo(tmp_path)
    _write_pm(root, tests_passing="false")
    assert check_postmortem_honesty([], worktree_root=root) == []
