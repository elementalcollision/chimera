"""Pre-written contract test for v43 build-capability — target 2 of 3.

Charter: mind/research/v43-parallel-builds-design.md (parallel fan-out, N=3
independent single-file builds in one soak). Operator-authored, committed to
main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/numfmt.py — so these tests pass, WITHOUT touching chimera/cli.py, the
other two v43 targets, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a
clean assertion failure. Gated by CHIMERA_V40_GATE.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CHIMERA_V40_GATE"),
    reason="v43 build-capability gate; run with CHIMERA_V40_GATE=1",
)


def _fns():
    try:
        from chimera.numfmt import clamp, human_bytes
    except ImportError as exc:
        pytest.fail(f"chimera.numfmt not importable: {exc}")
    return human_bytes, clamp


# ── human_bytes: binary units; no decimal for bytes, one otherwise ─

def test_human_bytes_bytes():
    human_bytes, _ = _fns()
    assert human_bytes(0) == "0 B"
    assert human_bytes(512) == "512 B"


def test_human_bytes_kib():
    human_bytes, _ = _fns()
    assert human_bytes(1024) == "1.0 KiB"
    assert human_bytes(1536) == "1.5 KiB"


def test_human_bytes_mib_gib():
    human_bytes, _ = _fns()
    assert human_bytes(1048576) == "1.0 MiB"
    assert human_bytes(1572864) == "1.5 MiB"
    assert human_bytes(1073741824) == "1.0 GiB"


# ── clamp: bound x to [lo, hi], preserving numeric type/value ──────

def test_clamp_within():
    _, clamp = _fns()
    assert clamp(5, 0, 10) == 5
    assert clamp(5.5, 0, 10) == 5.5


def test_clamp_below():
    _, clamp = _fns()
    assert clamp(-1, 0, 10) == 0


def test_clamp_above():
    _, clamp = _fns()
    assert clamp(99, 0, 10) == 10
