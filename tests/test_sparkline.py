"""Pre-written contract test for the v41 build-capability probe.

Charter: mind/research/v41-sparkline-design.md. Operator-authored, committed
to main FAILING before the soak. Chimera's task is to create
chimera/sparkline.py with a ``render_sparkline`` function that makes these
tests pass — WITHOUT touching chimera/cli.py or any existing source.

Strict-mode probe: the design note names only this file's path; these
assertions ARE the spec. The 8-level ramp is "▁▂▃▄▅▆▇█" (U+2581…U+2588);
level = round((v - vmin) / (vmax - vmin) * 7); empty -> ""; all-equal
(incl. single) -> the lowest block for each. Test inputs deliberately avoid
.5 scale boundaries so the result is rounding-mode-independent.

Harness: pre-implementation chimera.sparkline does not exist; ``_render``
imports it lazily and converts a missing module to a clean assertion
failure (N failed, never a collection error). Gated by CHIMERA_V40_GATE so
it lands failing only under the gate env; default CI skips it.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CHIMERA_V40_GATE"),
    reason="v41 build-capability gate; run with CHIMERA_V40_GATE=1",
)

RAMP = "▁▂▃▄▅▆▇█"  # U+2581 .. U+2588


def _render(values):
    try:
        from chimera.sparkline import render_sparkline
    except ImportError as exc:  # module not created yet (pre-impl)
        pytest.fail(f"chimera.sparkline.render_sparkline not importable: {exc}")
    return render_sparkline(values)


def test_empty_is_empty_string():
    assert _render([]) == ""


def test_single_value_is_lowest_block():
    assert _render([42]) == "▁"


def test_flat_input_all_lowest():
    assert _render([5, 5, 5]) == "▁▁▁"


def test_two_point_min_max():
    assert _render([0, 7]) == "▁█"


def test_full_ramp():
    # 0..7 scaled by *7/7 land on exact integer levels 0..7.
    assert _render(list(range(8))) == RAMP


def test_sparse_non_uniform():
    # vmin=0 vmax=100: 1 -> round(0.07)=0 -> ▁ ; 100 -> █.
    assert _render([0, 1, 100]) == "▁▁█"


def test_negatives():
    # vmin=-100 vmax=100 range=200: -100->▁ ; 50 -> round(150/200*7=5.25)=5 -> ▆ ; 100 -> █.
    assert _render([-100, 50, 100]) == "▁▆█"
