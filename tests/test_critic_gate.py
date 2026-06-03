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


@pytest.fixture
def calib_ok(tmp_path):
    """Provision a clean calibration record so enforcement is permitted."""
    cg.write_calibration_record(tmp_path, total=27, false_approve=0,
                                false_reject=3, accuracy=0.89)


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


def test_recompute_approve_allows(tmp_path, monkeypatch, staged, calib_ok):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    assert d.allowed and d.source == "recomputed"
    assert d.escalation is None


def test_recompute_reject_then_escalation_approves_overrules(tmp_path, monkeypatch, staged, calib_ok):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False), escalator=_mock(True)))
    assert d.allowed is True               # lone false-reject overruled
    assert d.escalated is True
    assert d.verdict.approved is False and d.escalation.approved is True


def test_unparseable_escalation_does_not_rescue_reject(tmp_path, monkeypatch, staged, calib_ok):
    # The escalator returns an "approve" but with parsed=False (empty/garbled
    # text, e.g. the OpenRouter rung that returned empty in ADR 0162 item-7).
    # The PARSEABLE guard must keep it fail-closed: an unreadable escalation
    # cannot overrule a reject, so the commit is BLOCKED.
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False, concerns=["drops a branch"]),
        escalator=_mock(True, parsed=False)))
    assert d.allowed is False
    assert d.escalated is True               # escalation ran...
    assert d.escalation.approved is True     # ...and even "approved"...
    assert d.escalation.parsed is False      # ...but was unparseable → no rescue
    assert "could not be read" in d.reason   # accurate block messaging


def test_parseable_escalation_approve_rescues_reject(tmp_path, monkeypatch, staged, calib_ok):
    # The mirror case: a PARSEABLE approve from the escalator DOES rescue a lone
    # over-cautious reject (the false-reject path the gate is meant to absorb).
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False), escalator=_mock(True, parsed=True)))
    assert d.allowed is True
    assert d.escalated is True
    assert d.escalation.approved is True and d.escalation.parsed is True


def test_escalator_model_recorded_in_log(tmp_path, monkeypatch, staged, calib_ok):
    # Requirement 4: which escalator model was consulted is surfaced for audit.
    import json

    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    esc = _mock(False)
    esc.model_id = "claude-opus-4-7"  # the gate reads .model_id off the callable
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(False), escalator=esc))
    assert d.allowed is False and d.escalator_model == "claude-opus-4-7"
    row = json.loads((tmp_path / "state" / cg._GATE_LOG).read_text().splitlines()[-1])
    assert row["escalator_model"] == "claude-opus-4-7"
    assert row["escalation_parsed"] is True


def test_recompute_reject_confirmed_blocks(tmp_path, monkeypatch, staged, calib_ok):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False, concerns=["drops the digit case"]),
        escalator=_mock(False)))
    assert d.allowed is False              # both reject → blocked
    assert "ADR 0162" in d.reason and "digit" in d.reason
    assert cg._OVERRIDE_ENV in d.reason    # the escape valve is surfaced


def test_failclosed_unparseable_then_no_escalation_blocks(tmp_path, monkeypatch, staged, calib_ok):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    # reviewer fails to parse (provider garbage) and no escalator available.
    d = _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False, parsed=False), escalator=None))
    assert d.allowed is False
    assert "needs human review" in d.reason


# ── artifact path (hash-bound) ───────────────────────────────────────


def test_artifact_approved_allows_without_reviewer(tmp_path, monkeypatch, staged, calib_ok):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    cg.write_verdict_artifact(tmp_path, _DIFF, CriticVerdict(True, [], "ok"),
                              goal="g", model_id="m")

    async def _explode(_d):
        raise AssertionError("reviewer must not be called when a valid artifact exists")

    d = _run(cg.check_commit_critic(tmp_path, reviewer=_explode))
    assert d.allowed and d.source == "artifact"


def test_artifact_rejected_still_escalates(tmp_path, monkeypatch, staged, calib_ok):
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


# ── calibration-gated activation (ADR 0162) ─────────────────────────


def test_enforce_blocks_when_no_calibration_record(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    # No calibration record written → enforcement is not legitimate.
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    assert d.allowed is False and d.source == "calibration-unverified"
    assert "critic-calibrate" in d.reason


def test_enforce_blocks_when_calibration_dirty(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    cg.write_calibration_record(tmp_path, total=27, false_approve=1,
                                false_reject=2, accuracy=0.85)  # FA>0 → unsafe
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    assert d.allowed is False and d.source == "calibration-unverified"
    assert "false_approve=1" in d.reason


def test_override_bypasses_dirty_calibration(tmp_path, monkeypatch, staged):
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    monkeypatch.setenv(cg._OVERRIDE_ENV, "1")
    cg.write_calibration_record(tmp_path, total=27, false_approve=3,
                                false_reject=2, accuracy=0.8)
    d = _run(cg.check_commit_critic(tmp_path, reviewer=_mock(False)))
    assert d.allowed and d.source == "override"  # operator override is absolute


def test_calibration_clean_helper(tmp_path):
    ok, why = cg.calibration_clean(tmp_path)
    assert ok is False and "no calibration record" in why
    cg.write_calibration_record(tmp_path, total=27, false_approve=0,
                                false_reject=3, accuracy=0.89)
    ok, why = cg.calibration_clean(tmp_path)
    assert ok is True and "false_approve=0" in why


# ── decision ledger (ADR 0162) ───────────────────────────────────────


def test_gate_decisions_are_logged(tmp_path, monkeypatch, staged, calib_ok):
    import json

    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))            # allow
    _run(cg.check_commit_critic(
        tmp_path, reviewer=_mock(False), escalator=_mock(False)))          # block
    log = (tmp_path / "state" / cg._GATE_LOG).read_text().splitlines()
    rows = [json.loads(ln) for ln in log]
    assert len(rows) == 2
    assert rows[0]["allowed"] is True and rows[0]["approved"] is True
    assert rows[1]["allowed"] is False and rows[1]["escalation_approved"] is False


# ── gate invocation trace (finding #2 instrument) ───────────────────


def test_gate_trace_records_invocation(tmp_path, monkeypatch, staged, calib_ok):
    import json
    monkeypatch.setenv(cg._ENFORCE_ENV, "1")
    _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    dbg = tmp_path / "state" / "critic-gate-debug.jsonl"
    assert dbg.is_file(), "gate must leave an invocation trace"
    rows = [json.loads(ln) for ln in dbg.read_text().splitlines()]
    assert rows[0]["event"] == "enter" and rows[0]["enforce"] is True
    assert "ts" in rows[0]


def test_gate_trace_records_even_when_disabled(tmp_path, monkeypatch):
    import json
    monkeypatch.delenv(cg._ENFORCE_ENV, raising=False)
    _run(cg.check_commit_critic(tmp_path, reviewer=_mock(True)))
    rows = [json.loads(ln) for ln in
            (tmp_path / "state" / "critic-gate-debug.jsonl").read_text().splitlines()]
    assert rows[0]["event"] == "enter" and rows[0]["enforce"] is False


def test_gate_cost_prices_primary_and_escalator():
    """The gate-log now carries the REAL per-commit critic+escalator cost
    (value-assessment 2026-06-03) — the hidden tax the ACT spend line misses."""
    from chimera.core.critic import CriticVerdict
    from chimera.core.critic_gate import GateDecision, _call_cost_usd, _gate_cost
    # sonnet $3/$15 per M; opus $15/$75 per M.
    assert _call_cost_usd("claude-sonnet-4-6", 5000, 1000) == pytest.approx(0.03)
    assert _call_cost_usd("claude-opus-4-7", 8000, 2000) == pytest.approx(0.27)
    assert _call_cost_usd("unknown-model", 5000, 1000) == 0.0
    primary = CriticVerdict(approved=False, model_id="claude-sonnet-4-6",
                            input_tokens=5000, output_tokens=1000)
    esc = CriticVerdict(approved=True, model_id="claude-opus-4-7",
                        input_tokens=8000, output_tokens=2000)
    d = GateDecision(allowed=True, source="recomputed", verdict=primary,
                     escalation=esc, escalated=True)
    cost = _gate_cost(d)
    assert cost["primary"]["usd"] == pytest.approx(0.03)
    assert cost["escalator"]["usd"] == pytest.approx(0.27)
    assert cost["total_usd"] == pytest.approx(0.30)
