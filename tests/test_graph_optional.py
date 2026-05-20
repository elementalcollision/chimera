"""v4.62 (ADR 0081) — graph projection is now OPT-IN.

The 2026-05-20 ADR-0015 revisit (mind/overnight/adr-revisits.md)
flagged the Kuzu projection as "probably not [needed] as a core
dependency so early." This test pins the new gate semantics: default
OFF, opt in via ``CHIMERA_GRAPH_ENABLED``, legacy
``CHIMERA_AUTO_GRAPH_UPDATE_DISABLED`` still wins.
"""

from __future__ import annotations

import pytest

from chimera.core.loop import graph_projection_enabled


def _clear(monkeypatch):
    monkeypatch.delenv("CHIMERA_GRAPH_ENABLED", raising=False)
    monkeypatch.delenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", raising=False)


def test_default_off(monkeypatch):
    _clear(monkeypatch)
    assert graph_projection_enabled() is False


def test_explicit_off_value_is_off(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", "0")
    assert graph_projection_enabled() is False


def test_truthy_values_enable(monkeypatch):
    _clear(monkeypatch)
    for v in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", v)
        assert graph_projection_enabled() is True, f"value {v!r} should enable"


def test_falsy_values_disable(monkeypatch):
    _clear(monkeypatch)
    for v in ("0", "false", "no", "", "anything-else"):
        monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", v)
        assert graph_projection_enabled() is False, f"value {v!r} should disable"


def test_legacy_var_alone_does_not_enable(monkeypatch):
    """Operators with only the legacy CHIMERA_AUTO_GRAPH_UPDATE_DISABLED
    set (typically =1 to disable) keep their disabled behavior; they
    don't accidentally enable now that the default flipped."""
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "1")
    assert graph_projection_enabled() is False
    monkeypatch.setenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "0")
    assert graph_projection_enabled() is False


def test_legacy_var_forces_off_when_enabled(monkeypatch):
    """The legacy disable still wins over the new enable — back-compat
    for any operator who explicitly set the disable var."""
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "1")
    assert graph_projection_enabled() is False


def test_legacy_var_off_with_new_var_on_means_on(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_GRAPH_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "0")
    assert graph_projection_enabled() is True
