"""Tests for chimera.core.observability (v3.3)."""

from __future__ import annotations

import json
import logging
import time


from chimera.core import configure_logging, phase_timer


def test_phase_timer_records_elapsed():
    out: dict[str, float] = {}
    with phase_timer("test_phase") as o:
        time.sleep(0.01)
        out = o
    assert out["elapsed_ms"] >= 5.0


def test_phase_timer_warns_when_over_budget(caplog):
    with caplog.at_level(logging.WARNING, logger="chimera.phase"):
        with phase_timer("slow_phase", budget_ms=1.0):
            time.sleep(0.01)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("slow_phase" in r.message for r in warnings)


def test_configure_logging_json_mode_emits_valid_json(capsys, monkeypatch):
    monkeypatch.setenv("CHIMERA_LOG_JSON", "1")
    monkeypatch.setenv("CHIMERA_LOG_LEVEL", "INFO")
    configure_logging()
    logging.getLogger("chimera.test").info("hello world", extra={"k": "v"})
    err = capsys.readouterr().err.strip().splitlines()
    assert err, "expected at least one log line"
    obj = json.loads(err[-1])
    assert obj["msg"] == "hello world"
    assert obj["level"] == "INFO"
    assert obj["k"] == "v"
    # Reset to a normal formatter so other tests aren't affected.
    monkeypatch.delenv("CHIMERA_LOG_JSON", raising=False)
    configure_logging()


def test_configure_logging_is_idempotent():
    configure_logging()
    n1 = len(logging.getLogger().handlers)
    configure_logging()
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2
