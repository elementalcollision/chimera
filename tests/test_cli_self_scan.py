"""Self-origination chip 2 (ADR 0161): the `chimera self-scan` proposal verb.

PRINTS ONLY — it must never launch a soak. These tests pin the output (ranked
candidates + copy-pasteable soak lines, the proposal-only banner), the --limit
and --base wiring, and a real-repo integration run.
"""

from __future__ import annotations

import pathlib

from chimera import cli as _cli
from chimera.core import self_scan as _ss


def _cands(n):
    return [
        _ss.TaskCandidate(
            goal=f"fix the {k} ruff lint finding(s) in chimera/f{k}.py",
            files=[f"chimera/f{k}.py"], test=None, source="ruff",
            score=1.0 - k * 0.01,
        )
        for k in range(1, n + 1)
    ]


class _Args:
    base = "main"
    limit = 10


def test_empty_prints_no_candidates_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: [])
    rc = _cli._cmd_self_scan(_Args())
    assert rc == 0
    assert "no behaviour-neutral candidates" in capsys.readouterr().out


def test_prints_ranked_candidates_with_soak_lines(monkeypatch, capsys):
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands(3))
    rc = _cli._cmd_self_scan(_Args())
    out = capsys.readouterr().out
    assert rc == 0
    assert "3 candidate(s)" in out
    assert "PROPOSAL ONLY" in out
    assert out.count("bash scripts/real_task_soak.sh") == 3
    assert "does not launch soaks" in out  # the banner


def test_limit_caps_output(monkeypatch, capsys):
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands(5))

    class A(_Args):
        limit = 2
    _cli._cmd_self_scan(A())
    out = capsys.readouterr().out
    assert "showing 2" in out
    assert out.count("bash scripts/real_task_soak.sh") == 2


def test_base_flows_into_soak_command(monkeypatch, capsys):
    monkeypatch.setattr(_ss, "scan_repo", lambda *a, **k: _cands(1))

    class A(_Args):
        base = "develop"
    _cli._cmd_self_scan(A())
    assert 'TASK_BASE="develop"' in capsys.readouterr().out


# ── integration: the real verb on the real repo ─────────────────────


def test_real_self_scan_verb_runs(capsys):
    import os
    repo = pathlib.Path(__file__).resolve().parents[1]
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        rc = _cli.main(["self-scan", "--limit", "3"])
    finally:
        os.chdir(cwd)
    out = capsys.readouterr().out
    assert rc == 0
    # ruff may be absent in some envs → either real candidates or the empty note
    assert ("candidate(s)" in out) or ("no behaviour-neutral candidates" in out)
