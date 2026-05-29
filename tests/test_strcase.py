"""Pre-written contract test for v43 build-capability — target 1 of 3.

Charter: mind/research/v43-parallel-builds-design.md (parallel fan-out, N=3
independent single-file builds in one soak). Operator-authored, committed to
main FAILING before the soak. Chimera's task is to create ONE new module —
chimera/strcase.py — so these tests pass, WITHOUT touching chimera/cli.py, the
other two v43 targets, or any existing source.

These assertions ARE the spec. Lazy import converts a missing module to a
clean assertion failure (N failed, never a collection error). Gated by
CHIMERA_V40_GATE; one of three mutually independent v43 test files.
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
        from chimera.strcase import to_camel, to_snake
    except ImportError as exc:
        pytest.fail(f"chimera.strcase not importable: {exc}")
    return to_snake, to_camel


# ── to_snake: '_' before an uppercase preceded by lowercase/digit ──

def test_to_snake_camel():
    to_snake, _ = _fns()
    assert to_snake("CamelCase") == "camel_case"


def test_to_snake_acronym_simple_rule():
    # No interior uppercase has a lowercase predecessor → no underscores.
    to_snake, _ = _fns()
    assert to_snake("HTTPServer") == "httpserver"


def test_to_snake_mixed():
    to_snake, _ = _fns()
    assert to_snake("getHTTPResponseCode") == "get_httpresponse_code"


def test_to_snake_edges():
    to_snake, _ = _fns()
    assert to_snake("") == ""
    assert to_snake("already_snake") == "already_snake"


# ── to_camel: split '_', lower head, title the rest ────────────────

def test_to_camel_basic():
    _, to_camel = _fns()
    assert to_camel("camel_case") == "camelCase"


def test_to_camel_multi():
    _, to_camel = _fns()
    assert to_camel("a_b_c") == "aBC"


def test_to_camel_edges():
    _, to_camel = _fns()
    assert to_camel("") == ""
    assert to_camel("foo") == "foo"
