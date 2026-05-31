"""Internal critic (thrust ③): adjudicate a change's faithfulness.

The faithfulness gate DETECTS behaviour problems but cannot ADJUDICATE the
correct direction when the suite is silent — that judgment is the critic's job,
a contract-free stand-in for human review. These tests pin the verdict parsing
(fail-closed), the prompt content, and the provider-driven review path with a
mock provider.
"""

from __future__ import annotations

import asyncio

from chimera.core.critic import (
    CriticVerdict,
    build_review_prompt,
    parse_verdict,
    review_change,
)


# ── parse_verdict: fail-closed ───────────────────────────────────────


def test_parse_approves_only_literal_true():
    v = parse_verdict('```json\n{"approved": true, "rationale": "faithful"}\n```')
    assert v.approved is True and v.parsed
    assert "APPROVED" in v.summary()


def test_parse_reject_with_concerns():
    v = parse_verdict(
        '```json\n{"approved": false, "concerns": ["drops isdigit branch"]}\n```'
    )
    assert v.approved is False
    assert v.concerns == ["drops isdigit branch"]
    assert "REJECTED" in v.summary()


def test_parse_bare_json_no_fence():
    v = parse_verdict('{"approved": true, "concerns": []}')
    assert v.approved is True


def test_parse_empty_is_failclosed():
    v = parse_verdict("")
    assert v.approved is False and v.parsed is False


def test_parse_garbage_is_failclosed():
    v = parse_verdict("the change looks fine to me, ship it")
    assert v.approved is False and v.parsed is False


def test_parse_missing_approved_key_is_failclosed():
    v = parse_verdict('```json\n{"rationale": "looks good"}\n```')
    assert v.approved is False and v.parsed is False


def test_parse_nonbool_approved_does_not_approve():
    # "yes"/1/"true" are not the literal boolean true → not an approval
    for val in ('"yes"', "1", '"true"'):
        v = parse_verdict(f'```json\n{{"approved": {val}}}\n```')
        assert v.approved is False, val


# ── prompt content ───────────────────────────────────────────────────


def test_prompt_includes_diff_intent_and_faithfulness():
    p = build_review_prompt(
        "diff-body-here",
        goal="fix to_snake",
        docstring="Inserts '_' ... lowercase or a digit.",
        faithfulness="behaviour delta: foo2Bar foo2_bar→foo2bar",
    )
    assert "diff-body-here" in p
    assert "fix to_snake" in p
    assert "lowercase or a digit" in p
    assert "foo2Bar" in p
    assert "faithful" in p.lower()
    assert "silent" in p.lower()
    assert "```json" in p


# ── review_change with a mock provider ───────────────────────────────


class _Provider:
    def __init__(self, text=None, raises=False):
        self._text = text
        self._raises = raises

    async def complete_with_tools(self, **kwargs):
        if self._raises:
            raise RuntimeError("boom")
        class _R:
            pass
        r = _R()
        r.text = self._text
        return r


def _review(prov):
    return asyncio.run(review_change("d", provider=prov, model_id="m"))


def test_review_approves_on_approve_verdict():
    v = _review(_Provider('```json\n{"approved": true}\n```'))
    assert v.approved is True


def test_review_rejects_on_reject_verdict():
    v = _review(_Provider('```json\n{"approved": false, "concerns": ["x"]}\n```'))
    assert v.approved is False


def test_review_failclosed_on_provider_error():
    v = _review(_Provider(raises=True))
    assert v.approved is False and v.parsed is False
    assert any("provider error" in c for c in v.concerns)


def test_review_failclosed_on_garbage_output():
    v = _review(_Provider("ship it!"))
    assert v.approved is False and v.parsed is False


def test_verdict_dataclass_summary_unparsed():
    v = CriticVerdict(False, parsed=False)
    assert "fail-closed" in v.summary()
