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

# ── prune ───────────────────────────────────────────────────

def _seed_aged_escalations(db_path: Path) -> None:
    """Seed 5 old rows (30 days ago) + 3 fresh rows (today)."""
    import sqlite3
    from datetime import UTC, datetime, timedelta

    db = sqlite3.connect(str(db_path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signature TEXT NOT NULL,
            task_text TEXT NOT NULL,
            tier TEXT NOT NULL,
            finish_reason TEXT NOT NULL,
            rounds_used INTEGER NOT NULL DEFAULT 0,
            cycle INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Dates are RELATIVE to wall-clock now so the 7-day prune window always
    # splits the two cohorts deterministically, regardless of run date.
    now = datetime.now(UTC)
    old_cutoff = (now - timedelta(days=30)).isoformat()
    with db:
        for i in range(5):
            db.execute(
                "INSERT INTO task_escalations "
                "(signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"old_sig_{i}", f"old task {i}", "haiku", "max_rounds", 5, 1, old_cutoff),
            )
    fresh_cutoff = (now - timedelta(days=1)).isoformat()
    with db:
        for i in range(3):
            db.execute(
                "INSERT INTO task_escalations "
                "(signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"fresh_sig_{i}", f"fresh task {i}", "sonnet", "stop", 3, 2, fresh_cutoff),
            )
    db.close()


def test_prune_text_output(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_aged_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("prune", "--older-than-days", "7", state_dir=state)
    assert rc == 0, f"stderr: {err}"
    assert "pruned 5 row(s)" in out, f"stdout: {out}"


def test_prune_json_output(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_aged_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("prune", "--older-than-days", "7", "--json", state_dir=state)
    assert rc == 0, f"stderr: {err}"
    payload = json.loads(out)
    assert payload == {"deleted": 5}, f"Unexpected payload: {payload}"


def test_prune_requires_older_than_days(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _seed_aged_escalations(state / "chimera.db")

    rc, out, err = _run_escalations("prune", state_dir=state)
    assert rc != 0, f"Should fail without --older-than-days, got rc={rc}"
    assert "older-than-days" in err.lower() or "error" in err.lower(), f"stderr: {err}"

