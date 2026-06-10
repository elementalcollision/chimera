"""Tests for v2.9 protocol journal + drift detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.a2a import (
    EvolutionKind,
    detect_protocol_drift,
    forget_peer,
    list_for_peer,
    record_observation,
    record_observations_from_registry,
)
from chimera.tools import ToolRegistry


def _schema(name, props):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {p: {"type": "string"} for p in props},
            },
        },
    }


@pytest.fixture
def journal_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "journal"
    monkeypatch.setenv("CHIMERA_PROTOCOL_JOURNAL_DIR", str(d))
    return d


# ── record + list ───────────────────────────────────────────


def test_record_observation_writes_line(journal_dir):
    record_observation(
        "chimera-alpha",
        "shell",
        _schema("shell", ["argv", "cwd"]),
        observed_at="2026-05-19T15:00:00+00:00",
    )
    files = list(journal_dir.glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].name == "chimera-alpha.jsonl"
    lines = files[0].read_text().splitlines()
    assert len(lines) == 1
    assert '"argv"' in lines[0] and '"cwd"' in lines[0]


def test_list_for_peer_returns_records_in_order(journal_dir):
    record_observation(
        "chimera-alpha",
        "shell",
        _schema("shell", ["argv"]),
        observed_at="2026-05-19T15:00:00+00:00",
    )
    record_observation(
        "chimera-alpha",
        "shell",
        _schema("shell", ["argv", "cwd"]),
        observed_at="2026-05-20T15:00:00+00:00",
    )
    recs = list_for_peer("chimera-alpha")
    assert [r.params for r in recs] == [("argv",), ("argv", "cwd")]


def test_list_for_peer_empty_for_unknown(journal_dir):
    assert list_for_peer("nobody") == []


def test_list_for_peer_skips_malformed_lines(journal_dir):
    record_observation(
        "chimera-alpha",
        "shell",
        _schema("shell", ["argv"]),
    )
    # Inject a bad line.
    path = journal_dir / "chimera-alpha.jsonl"
    path.write_text(path.read_text() + "not a json line\n")
    recs = list_for_peer("chimera-alpha")
    assert [r.tool for r in recs] == ["shell"]


def test_forget_peer_removes_file(journal_dir):
    record_observation("ghost", "shell", _schema("shell", ["argv"]))
    assert forget_peer("ghost") is True
    assert forget_peer("ghost") is False  # idempotent


def test_safe_filename_for_weird_agent_id(journal_dir):
    record_observation(
        "weird/peer:name",
        "shell",
        _schema("shell", ["argv"]),
    )
    files = list(journal_dir.glob("*.jsonl"))
    assert len(files) == 1
    # No slashes/colons in the filename.
    assert "/" not in files[0].name and ":" not in files[0].name


# ── record_observations_from_registry ───────────────────────


def test_record_observations_from_registry_picks_only_peer_tools(journal_dir):
    reg = ToolRegistry()

    async def _h(args, ctx):
        return ""

    for name, props in [
        ("mcp-alpha-shell", ["argv"]),
        ("mcp-alpha-code_exec", ["code"]),
        ("mcp-beta-shell", ["argv"]),
        ("local_tool", ["x"]),
    ]:
        reg.register(name=name, toolset="t", schema=_schema(name, props), handler=_h)

    written = record_observations_from_registry("alpha", reg)
    tools = {r.tool for r in written}
    assert tools == {"shell", "code_exec"}
    # beta and local_tool not touched.
    assert list_for_peer("beta") == []


# ── detect_protocol_drift ───────────────────────────────────


def test_drift_stable_when_baseline_equals_current(journal_dir):
    record_observation("p", "shell", _schema("shell", ["argv", "cwd"]))
    drift = detect_protocol_drift("p")
    assert len(drift) == 1
    assert drift[0].kind is EvolutionKind.STABLE


def test_drift_evolved_when_params_added(journal_dir):
    # Baseline.
    record_observation(
        "p",
        "shell",
        _schema("shell", ["argv"]),
        observed_at="2026-05-19T00:00:00+00:00",
    )
    # Current (from journal latest).
    record_observation(
        "p",
        "shell",
        _schema("shell", ["argv", "cwd", "timeout_s"]),
        observed_at="2026-05-20T00:00:00+00:00",
    )
    drift = detect_protocol_drift("p")
    assert len(drift) == 1
    rec = drift[0]
    assert rec.kind is EvolutionKind.EVOLVED
    assert rec.added_params == ("cwd", "timeout_s")
    assert rec.removed_params == ()


def test_drift_added_when_tool_only_in_current(journal_dir):
    record_observation("p", "shell", _schema("shell", ["argv"]))
    drift = detect_protocol_drift(
        "p", current_schemas={"shell": _schema("shell", ["argv"]), "code_exec": _schema("code_exec", ["code"])}
    )
    by_tool = {r.tool: r.kind for r in drift}
    assert by_tool["code_exec"] is EvolutionKind.ADDED
    assert by_tool["shell"] is EvolutionKind.STABLE


def test_drift_removed_when_tool_only_in_baseline(journal_dir):
    record_observation("p", "shell", _schema("shell", ["argv"]))
    record_observation("p", "old_tool", _schema("old_tool", ["x"]))
    # Current only has shell.
    drift = detect_protocol_drift(
        "p", current_schemas={"shell": _schema("shell", ["argv"])}
    )
    by_tool = {r.tool: r.kind for r in drift}
    assert by_tool["old_tool"] is EvolutionKind.REMOVED
    assert by_tool["shell"] is EvolutionKind.STABLE


def test_drift_empty_for_unknown_peer(journal_dir):
    assert detect_protocol_drift("nobody") == []


def test_drift_uses_earliest_as_baseline(journal_dir):
    """If a param exists at observation 1, disappears at 2, reappears at 3,
    drift vs earliest baseline should reflect the current state, not the
    middle window."""
    record_observation(
        "p", "shell", _schema("shell", ["argv", "cwd"]), observed_at="2026-05-19T00:00:00+00:00"
    )
    record_observation(
        "p", "shell", _schema("shell", ["argv"]), observed_at="2026-05-20T00:00:00+00:00"
    )
    record_observation(
        "p", "shell", _schema("shell", ["argv", "cwd", "timeout_s"]), observed_at="2026-05-21T00:00:00+00:00"
    )
    drift = detect_protocol_drift("p")
    rec = drift[0]
    assert rec.kind is EvolutionKind.EVOLVED
    # Baseline had [argv, cwd], latest has [argv, cwd, timeout_s].
    assert rec.added_params == ("timeout_s",)
    assert rec.removed_params == ()
