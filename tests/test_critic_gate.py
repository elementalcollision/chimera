"""ADR 0162: the in-loop critic enforcement gate.

Pins the gate's decision logic with injected reviewers (no live providers) and a
monkeypatched staged diff, plus the hash-bound verdict-artifact roundtrip and its
self-invalidation on a changed diff.
"""

from __future__ import annotations

import asyncio

import pytest

from chimera.core import critic_gate as cg
from chimera.core.critic import CriticVerdict

_DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"


def _run(coro):
    return asyncio.run(coro)


def _mock(approved: bool, *, parsed: bool = True, concerns=None):
    async def _r(_diff: str) -> CriticVerdict:
        return CriticVerdict(approved, concerns or [], "mock", parsed=parsed)
    return _r


@pytest.fixture
def staged(monkeypatch):
    """Force a non-empty staged diff regardless of the real index."""
    monkeypatch.setattr(cg, "staged_diff", lambda _root: _DIFF)
    monkeypatch.setattr(cg, "staged_files", lambda _root: ["x.py"])


# ── enforcement switch ───────────────────────────────────────────────


def test_disabled_by_default_allows(tmp_path, monkeypatch):
    monkeypatch.delenv(cg._ENFORCE_ENV, raising=False)
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(False)))
    assert d.allowed and d.source == "disabled"


def test_empty_diff_allows(tmp_path, monkeypatch):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    monkeypatch.setattr(cg, "staged_diff", lambda _root: "   \n")
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(False)))
    assert d.allowed and d.source == "empty-diff"


def test_override_allows_despite_reject(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    monkeypatch.setenv(cg._OVERRIDE_ENV, "1")
    called = False

    async def _never(_d):
        nonlocal called
        called = True
        return CriticVerdict(False)

    d = _run(cg.check_commit_critic(tmp_path, reviewer=_never))
    assert d.allowed and d.source == "override"
    assert called is False  # override short-circuits before any review


# ── recompute path (no artifact) ─────────────────────────────────────


def test_recompute_approve_allows(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    assert d.allowed and d.source == "recomputed"
    assert d.escalation is None


def test_recompute_reject_then_escalation_approves_overrules(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False), escalator=_mock(True)))
    assert d.allowed is True               # lone false-reject overruled
    assert d.escalated is True
    assert d.verdict.approved is False and d.escalation.approved is True


def test_recompute_reject_confirmed_blocks(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False, concerns=["drops the digit case"]),
        escalator=_mock(False)))
    assert d.allowed is False              # both reject → blocked
    assert "ADR 0162" in d.reason and "digit" in d.reason
    assert cg._OVERRIDE_ENV in d.reason    # the escape valve is surfaced


def test_failclosed_unparseable_then_no_escalation_blocks(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    # reviewer fails to parse (provider garbage) and no escalator available.
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False, parsed=False), escalator=None))
    assert d.allowed is False
    assert "needs human review" in d.reason


# ── artifact path (hash-bound) ───────────────────────────────────────


def test_artifact_approved_allows_without_reviewer(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    cg.write_verdict_artifact(tmp_path, _DIFF, CriticVerdict(True, [], "ok"),
                              goal="g", model_id="m")

    async def _explode(_d):
        raise AssertionError("reviewer must not be called when a valid artifact exists")

    d = _run(cg.check_commit_critic(tmp_path, reviewer=_explode))
    assert d.allowed and d.source == "artifact"


def test_artifact_rejected_still_escalates(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    cg.write_verdict_artifact(tmp_path, _DIFF, CriticVerdict(False, ["bad"]))
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(True), escalator=_mock(False)))
    # artifact says reject → goes to escalation (reviewer arg unused on this path)
    assert d.allowed is False and d.source == "artifact"


def test_artifact_hash_mismatch_is_ignored(tmp_path, monkeypatch):
    # An artifact written for a DIFFERENT diff must not satisfy the gate.
    cg.write_verdict_artifact(tmp_path, "OTHER DIFF", CriticVerdict(True))
    assert cg.load_verdict_artifact(tmp_path, _DIFF) is None


def test_artifact_roundtrip_matches(tmp_path):
    cg.write_verdict_artifact(tmp_path, _DIFF,
                              CriticVerdict(True, ["c1"], "why"), goal="g")
    v = cg.load_verdict_artifact(tmp_path, _DIFF)
    assert v is not None and v.approved and v.concerns == ["c1"] and v.rationale == "why"


def test_corrupt_artifact_returns_none(tmp_path):
    sha = cg.diff_sha(_DIFF)
    p = cg.artifact_path(tmp_path, sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert cg.load_verdict_artifact(tmp_path, _DIFF) is None


# ── staged_diff over a real index ────────────────────────────────────


def test_staged_diff_reads_the_index(tmp_path):
    import subprocess

    def r(*a):
        return subprocess.run(a, cwd=tmp_path, capture_output=True, text=True)

    r("git", "init", "-q")
    r("git", "config", "user.email", "t@t")
    r("git", "config", "user.name", "t")
    (tmp_path / "f.py").write_text("x = 1\n")
    r("git", "add", "f.py")
    diff = cg.staged_diff(tmp_path)
    assert "f.py" in diff and "+x = 1" in diff
    assert cg.staged_files(tmp_path) == ["f.py"]
