"""Graduation contract for TOOL_PREFILTER (ADR 0184) + COMPLEXITY_ROUTING (0185).

Both are opt-in (registry `default=None` → off). Graduation flips the registry
`default` None→"1" once a keyed flag-OFF/ON soak A/B, scored by
`chimera cost-delta`, shows the flag earns it (see each ADR for the criterion).

The default-ON tests below are the *pattern to activate at graduation*: un-skip
them, flip the registry default in `chimera/config.py`, and fill the ADR
Evidence section — in one PR. The explicit-disable tests are the opt-out
contract (ADR 0179) and are valid in BOTH states, so they run now.
"""

from __future__ import annotations

import pytest

from chimera.core.escalation import complexity_routing_enabled
from chimera.tools.tool_selection import tool_prefilter_enabled

_GRAD = "ADR 0184/0185: un-skip at graduation (registry default → '1' on cost-delta evidence)"


def test_tool_prefilter_default_on_after_graduation(monkeypatch):
    # GRADUATED 2026-06-19 (ADR 0184): registry default is now "1".
    monkeypatch.delenv("CHIMERA_TOOL_PREFILTER", raising=False)
    assert tool_prefilter_enabled() is True


@pytest.mark.skip(reason=_GRAD)
def test_complexity_routing_default_on_after_graduation(monkeypatch):
    monkeypatch.delenv("CHIMERA_COMPLEXITY_ROUTING", raising=False)
    assert complexity_routing_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "off", ""])
def test_tool_prefilter_explicit_disable(monkeypatch, val):
    """Opt-out holds regardless of the default (valid pre- and post-graduation)."""
    monkeypatch.setenv("CHIMERA_TOOL_PREFILTER", val)
    assert tool_prefilter_enabled() is False


@pytest.mark.parametrize("val", ["0", "false", "off", ""])
def test_complexity_routing_explicit_disable(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_COMPLEXITY_ROUTING", val)
    assert complexity_routing_enabled() is False
