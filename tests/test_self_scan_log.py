"""Self-origination precision log (ADR 0161 chip 3): record proposals + the
operator's accept/reject and compute origination precision — the labelled data
that eventually earns auto-origination.
"""

from __future__ import annotations

import pytest

from chimera.core.self_scan_log import (
    log_proposal,
    precision_report,
    proposal_id,
    record_decision,
)


def _log(tmp_path):
    return tmp_path / "proposals.jsonl"


def test_proposal_id_is_deterministic():
    a = proposal_id("fix lint in x.py", ["chimera/x.py"], "2026-05-31T00:00:00")
    b = proposal_id("fix lint in x.py", ["chimera/x.py"], "2026-05-31T00:00:00")
    c = proposal_id("fix lint in y.py", ["chimera/y.py"], "2026-05-31T00:00:00")
    assert a == b and a != c and len(a) == 8


def test_empty_log_is_clean_report(tmp_path):
    rep = precision_report(_log(tmp_path))
    assert rep.proposed == 0
    assert rep.precision == 0.0
    assert "no proposals logged" in rep.summary()


def test_log_and_decide_round_trip(tmp_path):
    log = _log(tmp_path)
    pid = log_proposal("fix lint in x.py", ["chimera/x.py"], "ruff", 1.0,
                       path=log, ts="2026-05-31T00:00:00")
    record_decision(pid, "accepted", path=log, ts="2026-05-31T00:01:00")
    rep = precision_report(log)
    assert rep.proposed == 1 and rep.accepted == 1 and rep.rejected == 0
    assert rep.precision == 1.0


def test_precision_over_mixed_decisions(tmp_path):
    log = _log(tmp_path)
    ids = []
    for i in range(4):
        ids.append(log_proposal(f"goal {i}", [f"f{i}.py"], "ruff", 0.9,
                                 path=log, ts=f"2026-05-31T00:0{i}:00"))
    record_decision(ids[0], "accepted", path=log, ts="t")
    record_decision(ids[1], "ran", path=log, ts="t")        # accept that executed
    record_decision(ids[2], "rejected", path=log, ts="t")
    # ids[3] left undecided
    rep = precision_report(log)
    assert rep.proposed == 4
    assert rep.accepted == 2 and rep.ran == 1 and rep.rejected == 1
    assert rep.undecided == 1
    assert rep.precision == 2 / 3   # 2 accepted of 3 decided


def test_latest_decision_wins(tmp_path):
    log = _log(tmp_path)
    pid = log_proposal("g", ["f.py"], "ruff", 1.0, path=log, ts="t0")
    record_decision(pid, "rejected", path=log, ts="t1")
    record_decision(pid, "accepted", path=log, ts="t2")   # revised
    rep = precision_report(log)
    assert rep.accepted == 1 and rep.rejected == 0


def test_reemitting_same_candidate_is_idempotent_by_id(tmp_path):
    log = _log(tmp_path)
    a = log_proposal("g", ["f.py"], "ruff", 1.0, path=log, ts="same")
    b = log_proposal("g", ["f.py"], "ruff", 1.0, path=log, ts="same")
    assert a == b
    # two proposal lines, same id → counted once
    assert precision_report(log).proposed == 1


def test_invalid_decision_raises(tmp_path):
    with pytest.raises(ValueError, match="decision must be"):
        record_decision("x", "maybe", path=_log(tmp_path), ts="t")


def test_malformed_line_is_skipped_not_raised(tmp_path):
    log = _log(tmp_path)
    log_proposal("g", ["f.py"], "ruff", 1.0, path=log, ts="t")
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    rep = precision_report(log)   # must not raise
    assert rep.proposed == 1
