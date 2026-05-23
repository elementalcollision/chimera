"""v4.95 — `chimera trust degrade-check` CLI verb.

ADR 0100 follow-up: soak runners call this between cycles to detect
mid-soak trust collapse (the soak v7 run-3 failure mode) and either
warn the operator or auto-promote the agent back above observer mode.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from chimera.trust import TrustManager
from chimera.trust.manager import TrustTier


def _run(*args: str, state_dir: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "trust", *args],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
        },
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _seed_at_t5(state_dir: Path) -> TrustManager:
    state_dir.mkdir(parents=True, exist_ok=True)
    tm = TrustManager(state_dir / "trust_state.json")
    tm.set_tier(TrustTier.T5, reason="test seed", kind="operator")
    return tm


def test_no_degradation_returns_zero(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed_at_t5(state)

    rc, out, _ = _run("degrade-check", "--baseline", "5", state_dir=state)
    assert rc == 0, out
    assert "ok" in out


def test_degradation_returns_warning_exit_code(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    tm.apply_finish_reason("scope_evasion")  # drops 2 tiers → T3

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--threshold-drop", "2",
        state_dir=state,
    )
    assert rc == 10, out
    assert "DEGRADED" in out
    assert "scope_evasion" in out


def test_t0_always_trips_warning(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    tm.set_tier(TrustTier.T0, reason="forced", kind="operator")

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--threshold-drop", "99",
        state_dir=state,
    )
    assert rc == 10, out
    assert "DEGRADED" in out


def test_auto_promote_lifts_above_t0_on_drift_demote(tmp_path: Path) -> None:
    """v4.119: drift-score demotes are still rescued by auto-promote."""
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    # Walk down five tiers via drift demotes so the latest history entry
    # has the rescuable "drift demote_plan:" prefix.
    for _ in range(5):
        tm.demote(reason="drift demote_plan: composite below threshold")

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--auto-promote", "--json",
        state_dir=state,
    )
    assert rc == 10, out
    payload = json.loads(out)
    assert payload["degraded"] is True
    assert payload["auto_promoted_to"] == 1
    assert payload["auto_promote_skipped_reason"] is None

    # Re-load TM to confirm persistence.
    tm2 = TrustManager(state / "trust_state.json")
    assert tm2.tier.value == 1


def test_auto_promote_sticky_on_detector_finding(tmp_path: Path) -> None:
    """v4.119: detector finish_reason demotes are NOT rescued."""
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    # Walk to T0 via repeated detector findings.
    for _ in range(5):
        tm.demote(
            reason="finish_reason=commit_message_diff_drift delta=1"
        )

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--auto-promote", "--json",
        state_dir=state,
    )
    assert rc == 10, out
    payload = json.loads(out)
    assert payload["degraded"] is True
    assert payload["auto_promoted_to"] is None
    assert payload["auto_promote_skipped_reason"] is not None
    assert "commit_message_diff_drift" in payload["auto_promote_skipped_reason"]

    # Re-load TM to confirm state stuck at T0.
    tm2 = TrustManager(state / "trust_state.json")
    assert tm2.tier.value == 0


def test_auto_promote_sticky_on_test_claim_invalid(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    for _ in range(5):
        tm.demote(reason="finish_reason=test_claim_invalid delta=1")

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--auto-promote", "--json",
        state_dir=state,
    )
    payload = json.loads(out)
    assert payload["auto_promoted_to"] is None
    assert "test_claim_invalid" in payload["auto_promote_skipped_reason"]


def test_auto_promote_sticky_on_scope_evasion(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    # scope_evasion demotes 2 tiers per firing — three to reach T0.
    for _ in range(3):
        tm.apply_finish_reason("scope_evasion")

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--auto-promote", "--json",
        state_dir=state,
    )
    payload = json.loads(out)
    assert payload["auto_promoted_to"] is None
    assert "scope_evasion" in payload["auto_promote_skipped_reason"]


def test_auto_promote_sticky_on_operator_demote(tmp_path: Path) -> None:
    """v4.119: operator-driven demotes are sticky — no auto-rescue."""
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    tm.set_tier(TrustTier.T0, reason="operator revoke", kind="operator")

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--auto-promote", "--json",
        state_dir=state,
    )
    payload = json.loads(out)
    assert payload["auto_promoted_to"] is None
    assert payload["auto_promote_skipped_reason"] is not None

    tm2 = TrustManager(state / "trust_state.json")
    assert tm2.tier.value == 0


def test_chronicle_warning_includes_finish_reason(tmp_path: Path) -> None:
    state = tmp_path / "state"
    chronicle = tmp_path / "SESSION_LOG.md"
    tm = _seed_at_t5(state)
    tm.apply_finish_reason("scope_evasion")

    rc, _, _ = _run(
        "degrade-check", "--baseline", "5",
        "--chronicle-path", str(chronicle),
        state_dir=state,
    )
    assert rc == 10
    assert chronicle.exists()
    body = chronicle.read_text()
    assert "trust degradation" in body
    assert "scope_evasion" in body
    assert "baseline=T5" in body


def test_no_degradation_does_not_write_chronicle(tmp_path: Path) -> None:
    state = tmp_path / "state"
    chronicle = tmp_path / "SESSION_LOG.md"
    _seed_at_t5(state)

    rc, _, _ = _run(
        "degrade-check", "--baseline", "5",
        "--chronicle-path", str(chronicle),
        state_dir=state,
    )
    assert rc == 0
    # File may be created empty by append_session_log? No — handler only
    # calls append_session_log when degraded.
    assert not chronicle.exists()


def test_json_payload_shape(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tm = _seed_at_t5(state)
    tm.apply_finish_reason("artifact_missing")  # 1-tier drop → T4

    rc, out, _ = _run(
        "degrade-check", "--baseline", "5", "--threshold-drop", "1",
        "--json", state_dir=state,
    )
    assert rc == 10
    payload = json.loads(out)
    assert payload["baseline_tier"] == 5
    assert payload["current_tier"] == 4
    assert payload["drop"] == 1
    assert payload["degraded"] is True
    assert payload["auto_promoted_to"] is None
    assert isinstance(payload["recent_demotes"], list)
    assert any(
        "artifact_missing" in ev["reason"] for ev in payload["recent_demotes"]
    )
