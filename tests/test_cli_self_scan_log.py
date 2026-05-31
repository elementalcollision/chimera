"""Self-origination chip 3 wiring: `chimera self-scan --log/--accept/--reject/
--precision` records proposals + decisions and reports origination precision.
"""

from __future__ import annotations

import re

from chimera import cli as _cli
from chimera.core import self_scan as _ss


def _cands():
    return [
        _ss.TaskCandidate(goal="fix lint in chimera/a.py", files=["chimera/a.py"],
                          test=None, source="ruff", score=1.0),
        _ss.TaskCandidate(goal="fix lint in chimera/b.py", files=["chimera/b.py"],
                          test=None, source="ruff", score=0.9),
    ]


def test_log_persists_and_prints_ids(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands())
    rc = _cli.main(["self-scan", "--log"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "id=" in out
    assert "Logged 2 proposal(s)" in out
    assert (tmp_path / "self_scan_proposals.jsonl").exists()


def test_accept_then_precision_round_trip(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands())
    _cli.main(["self-scan", "--log"])
    ids = re.findall(r"id=([a-f0-9]{8})", capsys.readouterr().out)
    assert len(ids) == 2

    _cli.main(["self-scan", "--accept", ids[0]])
    _cli.main(["self-scan", "--reject", ids[1]])
    capsys.readouterr()

    rc = _cli.main(["self-scan", "--precision"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "proposed 2" in out
    assert "accepted 1" in out and "rejected 1" in out
    assert "precision 50%" in out   # 1 accepted of 2 decided


def test_precision_on_empty_log(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path))
    rc = _cli.main(["self-scan", "--precision"])
    assert rc == 0
    assert "no proposals logged" in capsys.readouterr().out


def test_default_scan_without_log_writes_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands())
    _cli.main(["self-scan"])  # no --log
    assert not (tmp_path / "self_scan_proposals.jsonl").exists()
