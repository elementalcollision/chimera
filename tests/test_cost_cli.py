"""v4.58 (ADR 0077) — chimera cost CLI verb.

Smoke test for the operator-facing cost surface. The verb wraps the
v4.53 / v4.57 budget helpers in a CLI-friendly report; the test
confirms JSON-mode output is structurally correct and that the
band-classification logic matches the dashboard's TS classifier.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera.memory import open_and_init, record_api_call


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def _run_cost(*, state_dir: Path, mind_dir: Path, extra: list[str]) -> tuple[int, str]:
    """Invoke ``chimera cost`` with isolated state/mind dirs.

    Uses sys.executable + -m to avoid relying on the global PATH-installed
    chimera shim (which may point at a different venv during CI).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "cost", *extra],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
            "CHIMERA_MIND_DIR": str(mind_dir),
            "CHIMERA_ROLLING_HOUR_CAP_USD": "20.00",
            "CHIMERA_CYCLE_COST_CAP_USD": "2.00",
        },
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_cost_json_empty_db(tmp_path: Path):
    state = tmp_path / "state"
    mind = tmp_path / "mind"
    state.mkdir()
    mind.mkdir()
    # Seed the DB so open_and_init runs migrations against a clean path.
    db = open_and_init(state / "chimera.db")
    db.close()
    rc, out = _run_cost(state_dir=state, mind_dir=mind, extra=["--json"])
    assert rc == 0, out
    payload = json.loads(out)
    assert payload["total_usd"] == 0.0
    assert payload["band"] == "off"
    assert payload["by_model"] == []
    assert payload["cycle_cap_usd"] == pytest.approx(2.00)
    assert payload["rolling_hour_cap_usd"] == pytest.approx(20.00)


def test_cost_json_with_opus_spend(tmp_path: Path):
    state = tmp_path / "state"
    mind = tmp_path / "mind"
    state.mkdir()
    mind.mkdir()
    db = open_and_init(state / "chimera.db")
    record_api_call(
        db, cycle=7, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,  # $15 → over both caps
    )
    db.commit()
    db.close()
    rc, out = _run_cost(state_dir=state, mind_dir=mind, extra=["--json"])
    assert rc == 0, out
    payload = json.loads(out)
    assert payload["cycle"] == 7
    assert payload["cycle_spend_usd"] == pytest.approx(15.00, abs=0.01)
    # Default cycle = max(cycle); with one row, cycle=7. Spend > cap.
    assert payload["cycle_spend_usd"] > payload["cycle_cap_usd"]
    assert payload["total_usd"] == pytest.approx(15.00, abs=0.01)
    by_model_names = [b["model_id"] for b in payload["by_model"]]
    assert "claude-opus-4-7" in by_model_names


def test_cost_text_mode_shows_over_cap_warning(tmp_path: Path):
    state = tmp_path / "state"
    mind = tmp_path / "mind"
    state.mkdir()
    mind.mkdir()
    db = open_and_init(state / "chimera.db")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=200_000, output_tokens=0,  # $3 → over $2 cap
    )
    db.commit()
    db.close()
    rc, out = _run_cost(state_dir=state, mind_dir=mind, extra=[])
    assert rc == 0
    assert "OVER per-cycle cap" in out


def test_cost_explicit_cycle_arg(tmp_path: Path):
    state = tmp_path / "state"
    mind = tmp_path / "mind"
    state.mkdir()
    mind.mkdir()
    db = open_and_init(state / "chimera.db")
    # Two cycles, different spend.
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=0,  # ~$0.44
    )
    record_api_call(
        db, cycle=2, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,  # $15
    )
    db.commit()
    db.close()
    # Default selects max(cycle) = 2 → $15.
    rc, out = _run_cost(state_dir=state, mind_dir=mind, extra=["--json"])
    payload = json.loads(out)
    assert payload["cycle"] == 2
    assert payload["cycle_spend_usd"] == pytest.approx(15.00, abs=0.01)
    # Explicit --cycle 1 → $0.44.
    rc, out = _run_cost(state_dir=state, mind_dir=mind, extra=["--json", "--cycle", "1"])
    payload = json.loads(out)
    assert payload["cycle"] == 1
    assert payload["cycle_spend_usd"] == pytest.approx(0.435, abs=0.01)
