"""S1 / ADR 0153: self-charter generation, gated by the teeth check (ADR 0152).

Pins the parse (extract_charter), the teeth-gate (validate_charter accepts a
strong charter, rejects a weak or baseline-failing one), and the one-shot
orchestration (generate_charter) against a stub provider.
"""

from __future__ import annotations

import asyncio
import textwrap

from chimera.proposals.charter import (
    CharterBundle,
    build_charter_prompt,
    extract_charter,
    generate_charter,
    validate_charter,
)


def _charter_text(*, test_body: str, impl_body: str, module: str = "adder") -> str:
    # Concatenate verbatim — do NOT nest the multi-line bodies inside a
    # dedent()'d template (that mangles their indentation).
    return (
        "Sure, here is the charter:\n\n"
        "```charter-meta\n"
        f'{{"module_name": "{module}", "scope_paths": ["chimera/{module}.py"]}}\n'
        "```\n"
        "```charter-design\n"
        "Adds two ints and reports parity.\n"
        "```\n"
        "```charter-test\n" + test_body + "\n```\n"
        "```charter-impl\n" + impl_body + "\n```\n"
    )


_IMPL = textwrap.dedent(
    """
    def add(a, b):
        return a + b

    def is_even(n):
        return n % 2 == 0
    """
).strip()

_STRONG_TEST = textwrap.dedent(
    """
    import adder

    def test_add():
        assert adder.add(2, 3) == 5
        assert adder.add(-1, 1) == 0

    def test_even():
        assert adder.is_even(4) is True
        assert adder.is_even(3) is False
    """
).strip()

_WEAK_TEST = "def test_nothing():\n    assert True"


# ── extract_charter ─────────────────────────────────────────────────


def test_extract_parses_all_blocks():
    text = _charter_text(test_body=_STRONG_TEST, impl_body=_IMPL)
    b = extract_charter(text, goal="add ints")
    assert isinstance(b, CharterBundle)
    assert b.module_name == "adder"
    assert b.scope_paths == ["chimera/adder.py"]
    assert "def add" in b.reference_impl
    assert "def test_add" in b.acceptance_test
    assert b.design_note.startswith("Adds two ints")


def test_extract_returns_none_on_missing_block():
    # No impl block.
    text = "```charter-meta\n{\"module_name\": \"x\"}\n```\n```charter-test\nx\n```"
    assert extract_charter(text, goal="g") is None


def test_extract_returns_none_on_bad_meta_json():
    text = (
        "```charter-meta\nnot json\n```\n"
        "```charter-test\nx\n```\n```charter-impl\ny\n```"
    )
    assert extract_charter(text, goal="g") is None


def test_extract_rejects_non_identifier_module_name():
    text = _charter_text(test_body=_STRONG_TEST, impl_body=_IMPL, module="adder")
    text = text.replace('"adder"', '"not a name"', 1)
    assert extract_charter(text, goal="g") is None


# ── validate_charter (teeth gate) ───────────────────────────────────


def test_validate_accepts_strong_charter():
    b = extract_charter(_charter_text(test_body=_STRONG_TEST, impl_body=_IMPL), goal="g")
    v = validate_charter(b)
    assert v.ok, v.reason
    assert v.teeth is not None and v.teeth.teeth_score >= 0.8


def test_validate_rejects_weak_charter():
    b = extract_charter(_charter_text(test_body=_WEAK_TEST, impl_body=_IMPL), goal="g")
    v = validate_charter(b)
    assert v.ok is False
    assert "weak test" in v.reason
    assert v.teeth is not None and v.teeth.teeth_score == 0.0


def test_validate_rejects_baseline_failure():
    bad_test = "import adder\ndef test_bad():\n    assert adder.add(2, 3) == 999"
    b = extract_charter(_charter_text(test_body=bad_test, impl_body=_IMPL), goal="g")
    v = validate_charter(b)
    assert v.ok is False
    assert "does not pass its own test" in v.reason


def test_validate_rejects_unparseable_impl():
    b = CharterBundle(
        goal="g", module_name="brk",
        acceptance_test="def test_x():\n    assert True",
        reference_impl="def f(:\n    pass",  # syntax error
    )
    v = validate_charter(b)
    assert v.ok is False
    assert "unparseable" in v.reason


# ── generate_charter (orchestration, stubbed provider) ──────────────


class _StubProvider:
    def __init__(self, text: str) -> None:
        self._text = text

    async def complete_with_tools(self, **kwargs):
        class _R:
            pass
        r = _R()
        r.text = self._text
        return r


def test_generate_charter_strong():
    text = _charter_text(test_body=_STRONG_TEST, impl_body=_IMPL)
    bundle, val = asyncio.run(
        generate_charter("add ints", provider=_StubProvider(text), model_id="m")
    )
    assert bundle is not None and bundle.module_name == "adder"
    assert val.ok, val.reason


def test_generate_charter_no_usable_output():
    bundle, val = asyncio.run(
        generate_charter("g", provider=_StubProvider("sorry, no charter"), model_id="m")
    )
    assert bundle is None
    assert val.ok is False


def test_generate_charter_weak_is_surfaced_not_accepted():
    text = _charter_text(test_body=_WEAK_TEST, impl_body=_IMPL)
    bundle, val = asyncio.run(
        generate_charter("g", provider=_StubProvider(text), model_id="m")
    )
    assert bundle is not None       # parseable…
    assert val.ok is False          # …but rejected by the teeth gate


def test_build_charter_prompt_includes_goal():
    p = build_charter_prompt("build a widget counter")
    assert "build a widget counter" in p
    assert "charter-meta" in p and "charter-test" in p and "charter-impl" in p
