"""v4.110 — `chimera escalations list --json` and `escalations summary --json` tests.

CHARTER (ADR 0036 pattern):
  1. SCOPE: only --json on list and summary. NOT on clear.
  2. SCHEMA: same fields as existing formatted view.
  3. PATTERN: follows tiers --json (action="store_true", json.dumps indent=2 default=str).
  4. NO new SQL queries. Reuses existing queries.
  5. NO refactor of unrelated handlers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chimera.core.escalation import record_failure
from chimera.memory import open_and_init


def _run_escalations(*args: str, state_dir: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "escalations", *args],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
        },
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _seed_escalations(db_path: Path) -> None:
    """Seed a few escalation rows for testing."""
    db = open_and_init(db_path)
    record_failure(db, task_text="build agonistic futures world model artifact",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=12, cycle=1)
    record_failure(db, task_text="build agonistic futures world model artifact",
                   tier="sonnet", finish_reason="artifact_missing",
                   rounds_used=18, cycle=2)
    record_failure(db, task_text="compute fibonacci sequence quickly",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=8, cycle=3)
    db.close()


# ── list --json ──────────────────────────────────────────────

def test_escalations_list_json_outputs_valid_json(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("list", "--json", state_dir=state)
    assert rc == 0, err
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert len(payload) == 3
    row = payload[0]
    # ADR 0036 schema: same fields as existing formatted view
    for key in ("id", "signature", "task_text", "tier", "finish_reason",
                "rounds_used", "cycle", "created_at"):
        assert key in row, f"Missing key {key!r} in list row"


# ── list without --json (regression) ────────────────────────

def test_escalations_list_without_json_unchanged(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("list", state_dir=state)
    assert rc == 0, err

    fixture_path = Path(__file__).parent / "cli_expected" / "test_escalations_list.txt"
    expected = fixture_path.read_text()
    # Normalise cycle numbers (they can vary between runs on the soak branch).
    import re
    normalised_out = re.sub(r'cycle\s+\d+', 'cycle N', out)
    normalised_expected = re.sub(r'cycle\s+\d+', 'cycle N', expected)
    assert normalised_out == normalised_expected, (
        f"Formatted output diverged!\n"
        f"GOT:\n{out}\n"
        f"EXPECTED:\n{expected}"
    )


# ── summary --json ──────────────────────────────────────────

def test_escalations_summary_json_outputs_valid_json(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("summary", "--json", state_dir=state)
    assert rc == 0, err
    payload = json.loads(out)
    assert isinstance(payload, dict)
    # Should have at least one signature entry
    assert len(payload) >= 1
    for sig, tiers in payload.items():
        assert isinstance(tiers, dict)
        for tier, count in tiers.items():
            assert isinstance(count, int)


# ── clear has no --json ─────────────────────────────────────

def test_escalations_clear_has_no_json_flag(tmp_path: Path) -> None:
    """--json on clear must be rejected per charter."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("clear", "--all", "--json", state_dir=state)
    # Should fail because --json is not a recognised argument on clear
    assert rc != 0, (
        f"clear should reject --json!\nGOT rc={rc}\nout={out}\nerr={err}"
    )


# ── list with grep + json ───────────────────────────────────

def test_escalations_list_json_with_grep(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_escalations(state / "chimera.db")

    rc, out, err = _run_escalations(
        "list", "--json", "--grep", "agonistic", state_dir=state,
    )
    assert rc == 0, err
    payload = json.loads(out)
    assert len(payload) == 2
    for row in payload:
        assert "agonistic" in row["task_text"]
