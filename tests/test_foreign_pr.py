"""Tests for ADR 0186 B.4b/B.4c — trust-gated foreign DRAFT PR + approval gate.

Every gate is unit-tested via the ``submit_fn`` seam (no git/gh). Safety
invariants: the submit path is reached ONLY when every gate passes; it is always
called with ``draft=True`` + the foreign target; the first 5 foreign PRs need an
explicit per-PR approval grant; and the verify_cmd-review gate is fail-closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.core.foreign_pr_ledger import (
    count_foreign_prs_opened,
    record_foreign_pr_opened,
    record_verify_cmd_review,
)
from chimera.core.self_pr import maybe_foreign_pr
from chimera.core.submit_pr import SubmitPrResult

REPO = "elementalcollision/claude-daemon"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Deterministic: clear every foreign-PR env knob (env-leakage hygiene)."""
    for k in ("CHIMERA_FOREIGN_PR", "CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL",
              "CHIMERA_FOREIGN_PR_APPROVED", "CHIMERA_REPO_ALLOWLIST"):
        monkeypatch.delenv(k, raising=False)


def _spy(ok: bool = True):
    calls = []

    def fn(**kwargs):
        calls.append(kwargs)
        return SubmitPrResult(ok=ok, branch="chimera-soak/realtask-x",
                              pr_url="https://github.com/o/r/pull/1" if ok else None)

    fn.calls = calls
    return fn


def _trust(tmp_path: Path, tier: int) -> Path:
    p = tmp_path / "trust_state.json"
    p.write_text(json.dumps({"current_tier": tier}))
    return p


def _worktree_with_gate(tmp_path: Path, *, allowed: bool = True) -> Path:
    wt = tmp_path / "wt"
    (wt / "state").mkdir(parents=True, exist_ok=True)
    (wt / "state" / "critic-gate-log.jsonl").write_text(
        json.dumps({"allowed": allowed}) + "\n"
    )
    return wt


def _call(tmp_path, monkeypatch, *, spy=None, reviewed=True, **over):
    """Drive maybe_foreign_pr with all gates green unless overridden.

    Defaults are built ONLY when the test didn't override them (via pop) — the
    fixtures write to fixed paths, so building an unused default would clobber a
    test's override of the same path.
    """
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    state_dir = Path(over.pop("state_dir", None) or (tmp_path / "state"))
    state_dir.mkdir(exist_ok=True)
    foreign_repo = over.pop("foreign_repo", REPO)
    if reviewed:
        record_verify_cmd_review(state_dir, foreign_repo, ts="t0")
    worktree = over.pop("worktree", None) or _worktree_with_gate(tmp_path, allowed=True)
    trust_state_path = over.pop("trust_state_path", None) or _trust(tmp_path, 4)
    spy = spy or _spy()
    kw = dict(
        worktree=worktree,
        repo_root=tmp_path,
        foreign_repo=foreign_repo,
        foreign_base="main",
        state_dir=state_dir,
        trust_state_path=trust_state_path,
        submit_fn=spy,
    )
    kw.update(over)  # remaining: dry_run, run_id, foreign_base
    return maybe_foreign_pr(**kw), spy


# ── gates (fail-closed) ─────────────────────────────────────


def test_skips_when_foreign_pr_env_off(tmp_path, monkeypatch):
    # Autouse cleared the flag; do NOT set it.
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=_worktree_with_gate(tmp_path), repo_root=tmp_path,
        foreign_repo=REPO, trust_state_path=_trust(tmp_path, 5), submit_fn=spy,
    )
    assert not res.fired and "off by default" in res.skipped_reason
    assert spy.calls == []


def test_self_pr_flag_does_not_imply_foreign(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")  # must NOT enable foreign
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=_worktree_with_gate(tmp_path), repo_root=tmp_path,
        foreign_repo=REPO, trust_state_path=_trust(tmp_path, 5), submit_fn=spy,
    )
    assert not res.fired and spy.calls == []


def test_skips_when_repo_not_allowlisted(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, foreign_repo="evilcorp/malware")
    assert not res.fired and "not in CHIMERA_REPO_ALLOWLIST" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_trust_below_t4(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, trust_state_path=_trust(tmp_path, 3))
    assert not res.fired and "foreign-PR floor" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_no_gate_approved_commit(tmp_path, monkeypatch):
    wt = _worktree_with_gate(tmp_path, allowed=False)
    res, spy = _call(tmp_path, monkeypatch, worktree=wt)
    assert not res.fired and "no gate-approved commit" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_verify_cmd_not_reviewed(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, reviewed=False)
    assert not res.fired and "not operator-reviewed" in res.skipped_reason
    assert spy.calls == []


# ── approval gate (first 5) ─────────────────────────────────


def test_skips_when_approval_required_and_not_granted(tmp_path, monkeypatch):
    # REQUIRE_APPROVAL defaults ON; count 0 < 5; no grant → skip.
    res, spy = _call(tmp_path, monkeypatch)
    assert not res.fired and "needs operator approval" in res.skipped_reason
    assert "1/5" in res.skipped_reason
    assert spy.calls == []


def test_fires_when_approval_granted(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch)
    assert res.fired and res.submit.ok
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["foreign_repo"] == REPO
    assert call["draft"] is True
    assert call["foreign_base"] == "main"


def test_fires_when_approval_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL", "0")
    res, spy = _call(tmp_path, monkeypatch)  # no grant, but approval off
    assert res.fired and len(spy.calls) == 1


def test_graduates_after_floor_reached(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for i in range(5):  # 5 prior foreign PRs → graduated, no grant needed
        record_foreign_pr_opened(state_dir, REPO, f"r{i}", ts=f"t{i}")
    res, spy = _call(tmp_path, monkeypatch, state_dir=state_dir)
    assert res.fired and len(spy.calls) == 1


def test_records_foreign_pr_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert count_foreign_prs_opened(state_dir) == 0
    res, _ = _call(tmp_path, monkeypatch, state_dir=state_dir, run_id="run-42")
    assert res.fired
    assert count_foreign_prs_opened(state_dir) == 1


def test_does_not_record_on_submit_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    res, _ = _call(tmp_path, monkeypatch, state_dir=state_dir, spy=_spy(ok=False))
    assert res.fired and not res.submit.ok
    assert count_foreign_prs_opened(state_dir) == 0  # failed PR not counted


def test_dry_run_does_not_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    res, spy = _call(tmp_path, monkeypatch, state_dir=state_dir, dry_run=True)
    assert res.fired
    assert spy.calls[0]["dry_run"] is True
    assert count_foreign_prs_opened(state_dir) == 0
