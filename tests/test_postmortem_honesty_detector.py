"""Sub-chip 2 (v40′ scope-creep sprint): postmortem-honesty gate.

A written postmortem whose READY-FOR-REMEDIATION `tests_passing` claim
contradicts the test-run ledger is rejected at WRITE time (in the ACT
gate), catching the sub-agent-draft-dishonesty class before acceptance
rather than via a later manual cross-check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.act import check_postmortem_honesty
from chimera.core.remediation import derive_remediation_hint
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.soak_ledger import record_test_run

_RUN = "CHIMERA_SOAK_RUN_ID"


def _postmortem(tmp_path: Path, tests_passing: str) -> str:
    p = tmp_path / "mind" / "research" / "pm.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# postmortem\n\n## READY-FOR-REMEDIATION\n"
        "verdict: CONVERGED\nfiles_changed: 1\n"
        f"tests_passing: {tests_passing}\nact_cycles: 2\n"
    )
    return str(p)


def test_noop_outside_soak(tmp_path, monkeypatch):
    monkeypatch.delenv(_RUN, raising=False)
    assert check_postmortem_honesty([_postmortem(tmp_path, "true")]) == []


def test_flags_false_claim_when_ledger_shows_passing(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "runX")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=0, duration_ms=5.0, stdout="5 passed")
    # Claim false, ledger true → contradiction.
    f = check_postmortem_honesty([_postmortem(tmp_path, "false")])
    assert len(f) == 1 and "ledger shows" in f[0][1].lower() or "did pass" in f[0][1].lower()


def test_flags_true_claim_when_no_passing_run(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "runY")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=1, duration_ms=5.0, stdout="5 failed")
    f = check_postmortem_honesty([_postmortem(tmp_path, "true")])
    assert len(f) == 1


def test_honest_claim_passes(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "runZ")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=0, duration_ms=5.0, stdout="5 passed")
    assert check_postmortem_honesty([_postmortem(tmp_path, "true")]) == []


def test_non_postmortem_md_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "runW")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=1, duration_ms=5.0, stdout="x")
    # A doc with no READY block / tests_passing line is not a postmortem.
    d = tmp_path / "mind" / "notes.md"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text("# just notes\nno ready block here\n")
    assert check_postmortem_honesty([str(d)]) == []


def test_wired_into_recovery_and_trust():
    assert "postmortem_dishonest" in ESCALATING_FINISH_REASONS
    assert FINISH_REASON_TRUST_DELTAS.get("postmortem_dishonest") == 1
    hint = derive_remediation_hint("write postmortem", "postmortem_dishonest")
    assert hint and "tests_passing" in hint


# ── H2: verdict↔ledger coherence ─────────────────────────────────

def _postmortem_verdict(tmp_path: Path, verdict: str, tests_passing: str) -> str:
    p = tmp_path / "mind" / "research" / "pm.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# postmortem\n\n## READY-FOR-REMEDIATION\n"
        f"verdict: {verdict}\nfiles_changed: 1\n"
        f"tests_passing: {tests_passing}\nact_cycles: 2\n"
    )
    return str(p)


def test_converged_without_passing_run_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "h2a")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=1, duration_ms=5.0, stdout="1 failed")
    # tests_passing:false matches ledger (no Rule-A trip), but CONVERGED is unearned.
    f = check_postmortem_honesty([_postmortem_verdict(tmp_path, "CONVERGED", "false")])
    assert len(f) == 1 and "CONVERGED" in f[0][1]


def test_converged_with_passing_run_ok(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "h2b")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=0, duration_ms=5.0, stdout="6 passed")
    assert check_postmortem_honesty([_postmortem_verdict(tmp_path, "CONVERGED", "true")]) == []


def test_failed_verdict_with_no_passing_run_ok(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "h2c")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=1, duration_ms=5.0, stdout="1 failed")
    # FAILED + tests_passing:false + no passing run → coherent, not flagged.
    assert check_postmortem_honesty([_postmortem_verdict(tmp_path, "FAILED", "false")]) == []
