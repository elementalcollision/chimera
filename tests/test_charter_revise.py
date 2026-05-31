"""A2 (testability seams) + A3 (critique-and-revise) for self-charters."""

from __future__ import annotations

import asyncio

from chimera.proposals.charter import (
    build_charter_prompt,
    build_charter_revision_prompt,
    extract_charter,
    generate_charter,
)

_IMPL = "def add(a, b):\n    return a + b\n\ndef is_even(n):\n    return n % 2 == 0"
_STRONG_TEST = (
    "import adder\n"
    "def test_add(): assert adder.add(2, 3) == 5 and adder.add(-1, 1) == 0\n"
    "def test_even(): assert adder.is_even(4) is True and adder.is_even(3) is False"
)
_WEAK_TEST = "def test_nothing():\n    assert True"


def _charter(test_body: str) -> str:
    return (
        "```charter-meta\n"
        '{"module_name": "adder", "scope_paths": ["chimera/adder.py"]}\n```\n'
        "```charter-design\nAdds ints.\n```\n"
        "```charter-test\n" + test_body + "\n```\n"
        "```charter-impl\n" + _IMPL + "\n```\n"
    )


class _SeqProvider:
    """Returns a fixed sequence of completion texts, one per call."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    async def complete_with_tools(self, **kwargs):
        self.calls += 1
        text = self._texts.pop(0) if self._texts else ""
        class _R:
            pass
        r = _R()
        r.text = text
        return r


def _gen(prov, **kw):
    return asyncio.run(generate_charter("add ints", provider=prov, model_id="m", **kw))


# ── A3: critique-and-revise ─────────────────────────────────────────


def test_revise_recovers_a_weak_charter():
    prov = _SeqProvider([_charter(_WEAK_TEST), _charter(_STRONG_TEST)])
    bundle, val = _gen(prov, max_revisions=1)
    assert val.ok, val.reason
    assert prov.calls == 2  # one revise pass was used


def test_revise_exhausted_returns_last_failure():
    prov = _SeqProvider([_charter(_WEAK_TEST), _charter(_WEAK_TEST)])
    bundle, val = _gen(prov, max_revisions=1)
    assert val.ok is False
    assert prov.calls == 2
    assert bundle is not None  # surfaced for inspection


def test_no_revision_when_max_zero():
    prov = _SeqProvider([_charter(_WEAK_TEST), _charter(_STRONG_TEST)])
    bundle, val = _gen(prov, max_revisions=0)
    assert val.ok is False
    assert prov.calls == 1  # never revised


def test_first_try_ok_skips_revision():
    prov = _SeqProvider([_charter(_STRONG_TEST), _charter(_STRONG_TEST)])
    bundle, val = _gen(prov, max_revisions=1)
    assert val.ok
    assert prov.calls == 1  # no revision needed


def test_revision_recovers_from_no_usable_first_output():
    # First output unparseable → retry from scratch → strong.
    prov = _SeqProvider(["sorry, no charter", _charter(_STRONG_TEST)])
    bundle, val = _gen(prov, max_revisions=1)
    assert val.ok
    assert prov.calls == 2


# ── revision prompt content ─────────────────────────────────────────


def test_revision_prompt_feeds_back_surviving_mutants():
    weak = extract_charter(_charter(_WEAK_TEST), goal="g")
    from chimera.proposals.charter import validate_charter
    val = validate_charter(weak)  # weak → survivors recorded
    assert val.teeth is not None and val.teeth.survived
    prompt = build_charter_revision_prompt("g", weak, val)
    assert "too weak" in prompt
    assert "adder" in prompt  # keep same module
    # at least one surviving-mutant description is fed back
    assert any(s in prompt for s in val.teeth.survived)


def test_revision_prompt_handles_baseline_failure():
    bad_test = "import adder\ndef test_bad():\n    assert adder.add(2, 3) == 999"
    b = extract_charter(_charter(bad_test), goal="g")
    from chimera.proposals.charter import validate_charter
    val = validate_charter(b)
    assert val.ok is False and val.teeth is not None and not val.teeth.baseline_passed
    prompt = build_charter_revision_prompt("g", b, val)
    assert "does NOT pass your own" in prompt


# ── A2: testability seam in the base prompt ─────────────────────────


def test_prompt_instructs_testability_seam():
    p = build_charter_prompt("return the current unix timestamp")
    assert "TESTABILITY" in p
    assert "seam" in p.lower()
    assert "rng" in p.lower() or "clock" in p.lower()
