"""v4.71 (ADR 0090, P3) — proposer acceptance-rate scoring → demotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.proposer_scoring import (
    DEFAULT_THRESHOLD,
    ProposerDegradedError,
    all_scores,
    check_can_propose,
    compute_score,
    evaluate_and_update,
    get_status,
    list_statuses,
    pause,
    promote,
    scoring_enabled,
)
from chimera.memory import (
    approve_mutation,
    create_mutation,
    mark_applied,
    mark_failed,
    open_and_init,
    reject_mutation,
)


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _make(db, proposer: str, n: int):
    return [create_mutation(db, type=proposer, payload={"i": i}) for i in range(n)]


# ── master switch ────────────────────────────────────────────────


def test_scoring_default_on(monkeypatch):
    monkeypatch.delenv("CHIMERA_PROPOSER_SCORING_ENABLED", raising=False)
    assert scoring_enabled() is True


def test_scoring_off(monkeypatch):
    monkeypatch.setenv("CHIMERA_PROPOSER_SCORING_ENABLED", "0")
    assert scoring_enabled() is False


# ── compute_score ────────────────────────────────────────────────


def test_compute_score_empty(db):
    s = compute_score(db, "skill_proposal")
    assert s.decided == 0
    assert s.rate is None
    assert s.is_degraded is False


def test_compute_score_applied_and_rejected(db):
    ms = _make(db, "config_change", 5)
    mark_applied(db, ms[0].id)
    mark_applied(db, ms[1].id)
    reject_mutation(db, ms[2].id)
    reject_mutation(db, ms[3].id)
    mark_failed(db, ms[4].id, reason="boom")
    s = compute_score(db, "config_change")
    assert s.accepted == 2
    assert s.rejected == 3
    assert s.decided == 5
    assert s.rate == pytest.approx(0.4)


def test_compute_score_ignores_pending_and_expired(db):
    ms = _make(db, "skill_proposal", 4)
    mark_applied(db, ms[0].id)
    # ms[1], ms[2], ms[3] stay pending
    s = compute_score(db, "skill_proposal")
    assert s.accepted == 1
    assert s.decided == 1


def test_compute_score_window(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_PROPOSER_SCORE_WINDOW", "3")
    ms = _make(db, "task_split", 5)
    # Decisions in id order; window=3 looks at last 3 by id DESC.
    mark_applied(db, ms[0].id)
    mark_applied(db, ms[1].id)
    reject_mutation(db, ms[2].id)
    reject_mutation(db, ms[3].id)
    reject_mutation(db, ms[4].id)
    s = compute_score(db, "task_split")
    assert s.window == 3
    # Last 3 are ms[2], ms[3], ms[4] → all rejected.
    assert s.accepted == 0
    assert s.rejected == 3
    assert s.rate == 0.0


# ── evaluate_and_update / demote → degraded ──────────────────────


def test_evaluate_demotes_on_low_rate(db):
    ms = _make(db, "skill_proposal", 4)
    mark_applied(db, ms[0].id)
    reject_mutation(db, ms[1].id)
    reject_mutation(db, ms[2].id)
    reject_mutation(db, ms[3].id)
    # 1/4 = 25% < 50% → degraded.
    score, status = evaluate_and_update(db, "skill_proposal")
    assert score.rate == 0.25
    assert status is not None
    assert status.status == "degraded"
    assert "25%" in (status.reason or "")


def test_evaluate_keeps_active_on_high_rate(db):
    ms = _make(db, "config_change", 4)
    mark_applied(db, ms[0].id)
    mark_applied(db, ms[1].id)
    mark_applied(db, ms[2].id)
    reject_mutation(db, ms[3].id)
    score, status = evaluate_and_update(db, "config_change")
    assert score.rate == 0.75
    # No row written when actively healthy and no prior status.
    assert status is None


def test_evaluate_recovers_degraded(db):
    # First put it into degraded state.
    ms = _make(db, "config_change", 2)
    reject_mutation(db, ms[0].id)
    reject_mutation(db, ms[1].id)
    evaluate_and_update(db, "config_change")
    assert get_status(db, "config_change").status == "degraded"

    # Operator promotes to clear the degrade gate, then runs a healthy batch.
    promote(db, "config_change", reason="rewrote prompt")
    more = _make(db, "config_change", 4)
    mark_applied(db, more[0].id)
    mark_applied(db, more[1].id)
    mark_applied(db, more[2].id)
    mark_applied(db, more[3].id)
    # Window default = 10 → considers all 6: 4 applied + 2 rejected = 67%.
    _score, status = evaluate_and_update(db, "config_change")
    assert status.status == "active"
    assert "recovered" in (status.reason or "")


def test_paused_is_sticky(db):
    ms = _make(db, "skill_proposal", 4)
    mark_applied(db, ms[0].id)
    mark_applied(db, ms[1].id)
    mark_applied(db, ms[2].id)
    mark_applied(db, ms[3].id)
    pause(db, "skill_proposal", reason="manual")
    _score, status = evaluate_and_update(db, "skill_proposal")
    # Even with 100% rate, paused stays.
    assert status.status == "paused"


# ── gate behaviour through create_mutation ────────────────────────


def test_create_mutation_blocks_when_degraded(db):
    ms = _make(db, "skill_proposal", 2)
    reject_mutation(db, ms[0].id)
    reject_mutation(db, ms[1].id)
    # Score is 0%, but window default is 10 with only 2 decisions —
    # the rate is still computed and < 50% → degraded.
    assert get_status(db, "skill_proposal").status == "degraded"
    with pytest.raises(ProposerDegradedError):
        create_mutation(db, type="skill_proposal", payload={"x": 1})


def test_create_mutation_allowed_when_active(db):
    m = create_mutation(db, type="task_split", payload={"x": 1})
    assert m.id > 0
    assert m.status == "pending"


def test_create_mutation_blocked_when_paused(db):
    pause(db, "skill_proposal", reason="operator hold")
    with pytest.raises(ProposerDegradedError):
        create_mutation(db, type="skill_proposal", payload={"x": 1})


def test_check_can_propose_off_master_switch(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_PROPOSER_SCORING_ENABLED", "0")
    pause(db, "skill_proposal", reason="ignored when master off")
    allow, reason = check_can_propose(db, "skill_proposal")
    assert allow is True
    assert reason is None


# ── promote ──────────────────────────────────────────────────────


def test_promote_clears_degraded(db):
    ms = _make(db, "skill_proposal", 2)
    reject_mutation(db, ms[0].id)
    reject_mutation(db, ms[1].id)
    assert get_status(db, "skill_proposal").status == "degraded"
    st = promote(db, "skill_proposal", reason="rewrote prompt")
    assert st.status == "active"
    # Now create_mutation works again.
    m = create_mutation(db, type="skill_proposal", payload={"x": 1})
    assert m.id > 0


# ── env threshold override ───────────────────────────────────────


def test_per_proposer_threshold_env(db, monkeypatch):
    monkeypatch.setenv("CHIMERA_PROPOSER_CONFIG_CHANGE_THRESHOLD", "0.9")
    ms = _make(db, "config_change", 4)
    mark_applied(db, ms[0].id)
    mark_applied(db, ms[1].id)
    mark_applied(db, ms[2].id)  # 75%
    reject_mutation(db, ms[3].id)
    # Under default 50% this would be active; with threshold=0.9 → degraded.
    _score, status = evaluate_and_update(db, "config_change")
    assert status.status == "degraded"


# ── all_scores ───────────────────────────────────────────────────


def test_all_scores_lists_every_seen_type(db):
    a = _make(db, "skill_proposal", 1)
    b = _make(db, "task_split", 1)
    mark_applied(db, a[0].id)
    reject_mutation(db, b[0].id)
    scores = {s.proposer: s for s in all_scores(db)}
    assert set(scores.keys()) == {"skill_proposal", "task_split"}


# ── reeval is automatic on terminal transitions ───────────────────


def test_reeval_runs_on_reject(db):
    ms = _make(db, "skill_proposal", 2)
    reject_mutation(db, ms[0].id)
    # one reject so far: 0/1 = 0% < 50% → degraded.
    assert get_status(db, "skill_proposal").status == "degraded"


def test_check_can_propose_backfills_on_first_call(db):
    """v4.73 fix for ADR 0090 cold-start hole: a proposer that was
    already below threshold at install time (no terminal transition
    has fired since the hook was added) gets evaluated lazily on the
    first check_can_propose call rather than staying silently active.

    Reproduction from the 2026-05-20 long-cycle run: 4 failed +
    1 applied skill_proposal pre-existed; `chimera proposers list`
    showed 20% (live compute) but proposer_status was empty and
    create_mutation was happily allowing new proposals.
    """
    # Simulate pre-existing terminal state created BEFORE the hook
    # would have fired (we insert directly to skip the hook).
    db.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES ('skill_proposal', '{}', 'failed', 'pre-existing', "
        "datetime('now', '-1 day'))"
    )
    db.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES ('skill_proposal', '{}', 'failed', 'pre-existing', "
        "datetime('now', '-1 day'))"
    )
    db.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES ('skill_proposal', '{}', 'failed', 'pre-existing', "
        "datetime('now', '-1 day'))"
    )
    db.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES ('skill_proposal', '{}', 'applied', 'pre-existing', "
        "datetime('now', '-1 day'))"
    )
    # No proposer_status row yet — pre-fix behaviour would allow.
    assert get_status(db, "skill_proposal") is None

    allow, reason = check_can_propose(db, "skill_proposal")
    assert allow is False
    assert reason is not None
    assert "25%" in reason  # 1 applied of 4 decided
    # And now the status row exists for next time.
    st = get_status(db, "skill_proposal")
    assert st is not None
    assert st.status == "degraded"


def test_check_can_propose_backfill_allows_healthy(db):
    """Backfill path doesn't falsely demote a healthy proposer."""
    for _ in range(4):
        db.execute(
            "INSERT INTO mutations (type, payload, status, reason, created_at) "
            "VALUES ('config_change', '{}', 'applied', NULL, datetime('now', '-1 hour'))"
        )
    db.execute(
        "INSERT INTO mutations (type, payload, status, reason, created_at) "
        "VALUES ('config_change', '{}', 'rejected', NULL, datetime('now', '-1 hour'))"
    )
    allow, reason = check_can_propose(db, "config_change")
    assert allow is True
    assert reason is None


def test_listing_statuses(db):
    pause(db, "skill_proposal")
    pause(db, "task_split")
    rows = list_statuses(db)
    assert len(rows) == 2
    assert all(r.status == "paused" for r in rows)
