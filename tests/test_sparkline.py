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

from chimera.sparkline import render_sparkline

# v41 gate cleared (PR #151 soak, 2026-05-29): chimera/sparkline.py is now
# on main, so these contract tests run unconditionally in CI. The
# CHIMERA_V40_GATE skipif that let this file land FAILING before the build
# soak has been removed now that the implementation exists.

RAMP = "▁▂▃▄▅▆▇█"  # U+2581 .. U+2588


def _render(values):
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
