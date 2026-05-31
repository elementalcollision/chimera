"""B1: the `chimera verify` CLI verb wires the real-repo gate (ADR 0158).

The verb exposes `verify_change` as one command so the agent (or operator) can
run the repo's real checks and get a structured pass/fail + the actionable
failure detail. These tests pin the wiring (arg parsing → verify_change → exit
code), and one exercises the real `uv run ruff check` end to end.
"""

from __future__ import annotations

import pathlib

from chimera import cli as _cli
from chimera.core import repo_verify


def _patch_verify(monkeypatch, captured: dict, report):
    def fake(repo_root, **kwargs):
        captured["repo_root"] = repo_root
        captured.update(kwargs)
        return report
    monkeypatch.setattr(_cli, "verify_change", fake, raising=False)
    # _cmd_verify imports from chimera.core.repo_verify locally — patch there.
    monkeypatch.setattr(repo_verify, "verify_change", fake)


def test_verify_exit_zero_when_all_pass(monkeypatch, capsys):
    captured: dict = {}
    report = repo_verify.VerificationReport([repo_verify.CheckResult("ruff", True)])
    _patch_verify(monkeypatch, captured, report)
    rc = _cli.main(["verify"])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_verify_exit_one_and_prints_detail_on_failure(monkeypatch, capsys):
    captured: dict = {}
    report = repo_verify.VerificationReport([
        repo_verify.CheckResult("pytest", False, "the real failure text", 1),
    ])
    _patch_verify(monkeypatch, captured, report)
    rc = _cli.main(["verify"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "the real failure text" in err
    assert "pytest" in err


def test_verify_forwards_test_and_ruff_narrowing(monkeypatch, capsys):
    captured: dict = {}
    report = repo_verify.VerificationReport([repo_verify.CheckResult("ruff", True)])
    _patch_verify(monkeypatch, captured, report)
    rc = _cli.main([
        "verify", "--test", "tests/test_x.py",
        "--ruff", "chimera/x.py", "--ruff", "chimera/y.py",
        "--timeout", "42",
    ])
    assert rc == 0
    assert captured["test_target"] == "tests/test_x.py"
    assert captured["ruff_paths"] == ["chimera/x.py", "chimera/y.py"]
    assert captured["timeout"] == 42.0


def test_verify_runs_against_cwd(monkeypatch):
    captured: dict = {}
    report = repo_verify.VerificationReport([repo_verify.CheckResult("ruff", True)])
    _patch_verify(monkeypatch, captured, report)
    _cli.main(["verify"])
    assert pathlib.Path(captured["repo_root"]) == pathlib.Path.cwd()


# ── integration: the real verb runs the project's real ruff ─────────


def test_verify_verb_real_ruff_on_clean_file(monkeypatch, capsys):
    """End-to-end: `chimera verify --ruff <clean file>` exits 0 via real ruff,
    with pytest narrowed to a tiny always-green test to keep it fast."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    monkeypatch.chdir(repo)
    rc = _cli.main([
        "verify",
        "--ruff", "chimera/core/repo_verify.py",
        "--test", "tests/test_repo_verify.py::test_default_checks_are_ruff_then_pytest",
        "--timeout", "180",
    ])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out
