"""Drift chip (post-v42): postmortem numeric-honesty gate.

Promotes the READY-FOR-REMEDIATION ``act_cycles`` (Rule D) and ``spend_usd``
(Rule E) fields to CHECKED honesty fields. v40′/v41/v42 all drifted here —
v42 claimed ``act_cycles: 3`` / ``spend_usd: 0.02`` for a 15-cycle / $0.16
run — while the gate-checked ``tests_passing`` stayed honest. This was the
last un-closed honesty hole before the v43 parallel rung, where three
postmortems land at once and hand-auditing numbers is hardest.

Rule D ground truth = ``summarize_run().act_cycles`` (ledger). Rule E ground
truth = the run DB spend via ``_run_spend_usd_best_effort`` (fail-soft).
"""

from __future__ import annotations

from pathlib import Path

import chimera.core.act as act
from chimera.core.act import check_postmortem_honesty
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS

_RUN = "CHIMERA_SOAK_RUN_ID"


def _pm(tmp_path: Path, *, act_cycles: str = "15", spend_usd: str = "0.16",
        tests_passing: str = "true", verdict: str = "CONVERGED") -> str:
    p = tmp_path / "mind" / "research" / "pm.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# postmortem\n\n## READY-FOR-REMEDIATION\n"
        f"verdict: {verdict}\nfiles_changed: 2\n"
        f"tests_passing: {tests_passing}\n"
        f"spend_usd: {spend_usd}\nact_cycles: {act_cycles}\n"
    )
    return str(p)


def _arm(monkeypatch, *, act_cycles: int = 15, spend: float | None = None):
    """Make the soak active with a controlled ledger summary + DB spend."""
    monkeypatch.setenv(_RUN, "drift-run")
    monkeypatch.setattr(
        "chimera.core.soak_ledger.summarize_run",
        lambda *a, **k: {"tests_passed_any": True, "act_cycles": act_cycles},
    )
    monkeypatch.setattr(act, "_run_spend_usd_best_effort", lambda: spend)


# ── Rule D: act_cycles ───────────────────────────────────────────

def test_act_cycles_gross_drift_flagged(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=None)
    f = check_postmortem_honesty([_pm(tmp_path, act_cycles="3")])
    assert len(f) == 1 and "act_cycles" in f[0][1]


def test_act_cycles_within_band_passes(tmp_path, monkeypatch):
    # ledger 15, claim 14 → within max(2, 25%·15=4) band.
    _arm(monkeypatch, act_cycles=15, spend=None)
    assert check_postmortem_honesty([_pm(tmp_path, act_cycles="14")]) == []


def test_act_cycles_exact_passes(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=None)
    assert check_postmortem_honesty([_pm(tmp_path, act_cycles="15")]) == []


def test_act_cycles_small_run_off_by_two_tolerated(tmp_path, monkeypatch):
    # ledger 3, claim 5 → |2| == floor band 2 → allowed (not > band).
    _arm(monkeypatch, act_cycles=3, spend=None)
    assert check_postmortem_honesty([_pm(tmp_path, act_cycles="5")]) == []


def test_act_cycles_not_checked_when_ledger_zero(tmp_path, monkeypatch):
    # No ACT records yet (gt 0) → Rule D no-ops; can't establish truth.
    _arm(monkeypatch, act_cycles=0, spend=None)
    assert check_postmortem_honesty([_pm(tmp_path, act_cycles="99")]) == []


# ── Rule E: spend_usd ────────────────────────────────────────────

def test_spend_gross_under_report_flagged(tmp_path, monkeypatch):
    # the v42 case: claim $0.02, actual $0.16.
    _arm(monkeypatch, act_cycles=15, spend=0.16)
    f = check_postmortem_honesty([_pm(tmp_path, spend_usd="0.02")])
    assert len(f) == 1 and "spend_usd" in f[0][1]


def test_spend_over_report_flagged(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=0.16)
    f = check_postmortem_honesty([_pm(tmp_path, spend_usd="1.50")])
    assert len(f) == 1 and "spend_usd" in f[0][1]


def test_spend_close_enough_passes(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=0.16)
    assert check_postmortem_honesty([_pm(tmp_path, spend_usd="0.15")]) == []


def test_spend_deadband_protects_microruns(tmp_path, monkeypatch):
    # actual $0.03, claim $0.01 → 3× off but |0.02| < $0.05 deadband.
    _arm(monkeypatch, act_cycles=15, spend=0.03)
    assert check_postmortem_honesty([_pm(tmp_path, spend_usd="0.01")]) == []


def test_spend_unreadable_db_skips_rule(tmp_path, monkeypatch):
    # DB spend None → Rule E fail-soft, never blocks on an unverifiable number.
    _arm(monkeypatch, act_cycles=15, spend=None)
    assert check_postmortem_honesty([_pm(tmp_path, spend_usd="0.02")]) == []


def test_spend_nonpositive_db_skips_rule(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=0.0)
    assert check_postmortem_honesty([_pm(tmp_path, spend_usd="9.99")]) == []


# ── interaction + wiring ─────────────────────────────────────────

def test_tests_passing_takes_precedence_over_numeric(tmp_path, monkeypatch):
    # Rule A (tests_passing) is most severe; numeric drift is secondary.
    monkeypatch.setenv(_RUN, "drift-run")
    monkeypatch.setattr(
        "chimera.core.soak_ledger.summarize_run",
        lambda *a, **k: {"tests_passed_any": False, "act_cycles": 15},
    )
    monkeypatch.setattr(act, "_run_spend_usd_best_effort", lambda: 0.16)
    f = check_postmortem_honesty(
        [_pm(tmp_path, tests_passing="true", act_cycles="3", spend_usd="0.02")]
    )
    assert len(f) == 1 and "tests_passing" in f[0][1]


def test_fully_honest_postmortem_passes(tmp_path, monkeypatch):
    _arm(monkeypatch, act_cycles=15, spend=0.16)
    assert check_postmortem_honesty(
        [_pm(tmp_path, tests_passing="true", act_cycles="15", spend_usd="0.16")]
    ) == []


def test_numeric_drift_uses_postmortem_dishonest_wiring():
    # The detector reuses the existing finish_reason, already wired into
    # escalation + trust; no new reason string to thread through 4 sites.
    assert "postmortem_dishonest" in ESCALATING_FINISH_REASONS
    assert "postmortem_dishonest" in FINISH_REASON_TRUST_DELTAS
