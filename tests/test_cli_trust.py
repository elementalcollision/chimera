"""v4.94 — `chimera trust budget` CLI verb.

Read side of v4.93's finish_reason-keyed trust deltas (ADR 0100). Seeds
a TrustManager, demotes via apply_finish_reason("scope_evasion"), then
asserts the budget verb surfaces the finish_reason provenance.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from chimera.trust import TrustManager
from chimera.trust.manager import TrustTier


def _run_trust(*args: str, state_dir: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "trust", *args],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
        },
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _seed(state_dir: Path) -> TrustManager:
    state_dir.mkdir(parents=True, exist_ok=True)
    tm = TrustManager(state_dir / "trust_state.json")
    tm.set_tier(TrustTier.T5, reason="test seed", kind="operator")
    tm.apply_finish_reason("scope_evasion")
    return tm


def test_budget_text_includes_scope_evasion(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed(state)

    rc, out, err = _run_trust("budget", state_dir=state)
    combined = out + err

    assert rc == 0, combined
    assert "scope_evasion" in combined
    assert "finish_reason=" in combined
    assert "hours_in_tier" in combined
    assert "next promotion" in combined


def test_budget_json_shape(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _seed(state)

    rc, out, _ = _run_trust("budget", "--json", state_dir=state)
    assert rc == 0
    payload = json.loads(out)

    assert "tier" in payload
    assert "hours_in_tier" in payload
    assert "promotion_threshold" in payload
    assert "dwell_hours_required" in payload
    assert isinstance(payload["history"], list)
    assert any(
        "scope_evasion" in ev["reason"] for ev in payload["history"]
    ), payload["history"]


def test_budget_limit_truncates_history(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    tm = TrustManager(state / "trust_state.json")
    tm.set_tier(TrustTier.T5, reason="seed", kind="operator")
    for _ in range(6):
        tm.apply_finish_reason("artifact_missing")

    rc, out, _ = _run_trust("budget", "--limit", "2", "--json", state_dir=state)
    assert rc == 0
    payload = json.loads(out)
    assert len(payload["history"]) == 2
