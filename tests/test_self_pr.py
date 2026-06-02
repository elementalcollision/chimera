"""Tests for ADR 0163 trust-gated autonomous self-PR.

The four gates (opt-in env, trust ≥ T4, gate-approved commit, validated submit)
are unit-tested via the ``submit_fn`` seam so they never touch git/gh. The key
safety invariant: the submit path is reached ONLY when every gate passes, and it
is always called with ``draft=True``.
"""

from __future__ import annotations

import json
from pathlib import Path


from chimera.core.self_pr import maybe_self_pr
from chimera.core.submit_pr import SubmitPrResult


def _spy():
    calls = []

    def fn(**kwargs):
        calls.append(kwargs)
        return SubmitPrResult(ok=True, branch="chimera-soak/realtask-x")

    fn.calls = calls
    return fn


def _trust(tmp_path: Path, tier: int) -> Path:
    p = tmp_path / "trust_state.json"
    p.write_text(json.dumps({"current_tier": tier}))
    return p


def _worktree_with_gate(tmp_path: Path, *, allowed: bool) -> Path:
    wt = tmp_path / "wt"
    (wt / "state").mkdir(parents=True)
    (wt / "state" / "critic-gate-log.jsonl").write_text(
        json.dumps({"allowed": allowed, "escalated": False, "approved": allowed}) + "\n"
    )
    return wt


def test_skips_when_env_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("CHIMERA_SELF_PR", raising=False)
    spy = _spy()
    r = maybe_self_pr(
        worktree=_worktree_with_gate(tmp_path, allowed=True),
        repo_root=tmp_path,
        trust_state_path=_trust(tmp_path, 4),
        submit_fn=spy,
    )
    assert r.fired is False
    assert "off by default" in r.skipped_reason
    assert spy.calls == []  # submit never reached


def test_skips_when_trust_below_t4(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")
    spy = _spy()
    r = maybe_self_pr(
        worktree=_worktree_with_gate(tmp_path, allowed=True),
        repo_root=tmp_path,
        trust_state_path=_trust(tmp_path, 2),  # T2 < T4
        submit_fn=spy,
    )
    assert r.fired is False
    assert "T4" in r.skipped_reason
    assert spy.calls == []


def test_skips_when_no_gate_log(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")
    spy = _spy()
    wt = tmp_path / "wt"
    (wt / "state").mkdir(parents=True)  # no gate log written
    r = maybe_self_pr(
        worktree=wt, repo_root=tmp_path,
        trust_state_path=_trust(tmp_path, 4), submit_fn=spy,
    )
    assert r.fired is False
    assert "gate-approved" in r.skipped_reason
    assert spy.calls == []


def test_skips_when_last_gate_decision_not_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")
    spy = _spy()
    r = maybe_self_pr(
        worktree=_worktree_with_gate(tmp_path, allowed=False),  # blocked commit
        repo_root=tmp_path,
        trust_state_path=_trust(tmp_path, 5),
        submit_fn=spy,
    )
    assert r.fired is False
    assert spy.calls == []


def test_fires_draft_when_all_gates_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")
    spy = _spy()
    r = maybe_self_pr(
        worktree=_worktree_with_gate(tmp_path, allowed=True),
        repo_root=tmp_path,
        trust_state_path=_trust(tmp_path, 4),  # exactly T4 floor
        submit_fn=spy,
    )
    assert r.fired is True
    assert r.submit is not None and r.submit.ok is True
    assert len(spy.calls) == 1
    # The non-negotiable safety invariant: always draft, never merge.
    assert spy.calls[0]["draft"] is True
    # mind/* journal noise is excluded from the clean-tree check (soak integration).
    assert spy.calls[0]["ignore_dirty_prefixes"] == ("mind/",)
