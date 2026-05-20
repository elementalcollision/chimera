"""v4.55 (ADR 0074) — audit.py safety hardening.

Pins:
  * audit_ontology() returns a structured stub when the schema is
    incomplete, instead of raising sqlite3.OperationalError.
  * The dead-entity finding (A21) is documented in the ADR. This
    test asserts the CURRENT behaviour so a future fix has a
    regression target.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from chimera.memory.audit import audit_ontology


def test_audit_ontology_schema_missing_returns_stub(tmp_path: Path):
    """Empty SQLite (no tables) → structured stub, no raise."""
    conn = sqlite3.connect(tmp_path / "empty.db")
    conn.row_factory = sqlite3.Row
    try:
        result = audit_ontology(conn, current_cycle=10)
    finally:
        conn.close()
    assert result["error"] == "schema_missing"
    assert result["total_entities"] == 0
    assert result["stale_entities"] == []
    assert result["dead_entities"] == []
    assert "detail" in result


def test_audit_ontology_partial_schema_returns_stub(tmp_path: Path):
    """entities table present but agent_activity_log missing → stub."""
    conn = sqlite3.connect(tmp_path / "partial.db")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE entities (id TEXT, kind TEXT, name TEXT, "
            "kfm_state TEXT, state_entered_at_cycle INTEGER)"
        )
        result = audit_ontology(conn, current_cycle=10)
    finally:
        conn.close()
    # Some queries succeeded, some failed → must be flagged.
    assert result["error"] == "schema_missing"


def test_audit_ontology_full_schema_no_error_key(tmp_path: Path):
    """Healthy DB → no 'error' key in the result dict."""
    from chimera.memory import open_and_init
    conn = open_and_init(tmp_path / "healthy.db")
    try:
        result = audit_ontology(conn, current_cycle=10)
    finally:
        conn.close()
    assert "error" not in result
    assert result["total_entities"] == 0  # empty but valid
