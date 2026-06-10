"""v4.102 (ADR 0106): witness review for foundational code changes.

Covers the scope helper, the diff-capture helper, the verdict parser,
the wiring of ``witness_rejected`` into escalation / trust /
remediation, and the end-to-end ``witness_code_change`` call against
a stub provider. We do NOT exercise a real Anthropic call here —
that path is exercised in the soak runs.
"""

from __future__ import annotations

import asyncio
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _witness_rejected_hint,
    derive_remediation_hint,
)
from chimera.core.witness import (
    capture_diff_for_witness,
    parse_verdict,
    should_witness,
    witness_code_change,
    witness_enabled,
    witness_tier,
)
from chimera.providers.base import ChatChunk, ChatMessage, Provider
from chimera.providers.messages import ChatResponse, Message
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


# ── Stub provider ────────────────────────────────────────────────


class _StubProvider(Provider):
    """Captures the call args and yields a canned reply."""

    name = "stub"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model_id: str,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append(
            {"messages": messages, "model_id": model_id, "system": system}
        )

        async def _agen() -> AsyncIterator[ChatChunk]:
            yield ChatChunk(text=self.reply, finish_reason="stop")

        return _agen()

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:  # pragma: no cover
        raise NotImplementedError


# ── should_witness ───────────────────────────────────────────────


def test_should_witness_picks_chimera_python_paths() -> None:
    assert should_witness(["chimera/core/act.py"]) == ["chimera/core/act.py"]


def test_should_witness_picks_test_paths() -> None:
    assert should_witness(["tests/test_x.py"]) == ["tests/test_x.py"]


def test_should_witness_excludes_version_and_init() -> None:
    assert should_witness(["chimera/_version.py", "chimera/__init__.py"]) == []


def test_should_witness_skips_mind_writes() -> None:
    assert should_witness(["mind/research/foo.md", "mind/INBOX.md"]) == []


def test_should_witness_skips_state_writes() -> None:
    assert should_witness(["state/notes.md", "state/chimera.db"]) == []


def test_should_witness_skips_non_python() -> None:
    assert should_witness(["chimera/core/notes.md", "tests/fixtures/foo.txt"]) == []


def test_should_witness_mixed_input() -> None:
    paths = [
        "chimera/core/act.py",
        "mind/research/whatever.md",
        "tests/test_act.py",
        "chimera/_version.py",
        "docs/adr/0106.md",
    ]
    assert should_witness(paths) == ["chimera/core/act.py", "tests/test_act.py"]


# ── parse_verdict ────────────────────────────────────────────────


def test_parse_verdict_clean_approval() -> None:
    v = parse_verdict('{"approved": true, "concerns": [], "summary": "ok"}')
    assert v.approved is True
    assert v.concerns == []


def test_parse_verdict_rejection() -> None:
    v = parse_verdict(
        '{"approved": false, "concerns": ["foo.py: dangling return"], '
        '"summary": "broken"}'
    )
    assert v.approved is False
    assert v.concerns == ["foo.py: dangling return"]
    assert v.summary == "broken"


def test_parse_verdict_extracts_json_from_prose() -> None:
    text = "Here is my verdict:\n```json\n" + '{"approved": false, "concerns": ["x"]}' + "\n```"
    v = parse_verdict(text)
    assert v.approved is False
    assert v.concerns == ["x"]


def test_parse_verdict_caps_concerns_at_five() -> None:
    v = parse_verdict(
        '{"approved": false, "concerns": ["a","b","c","d","e","f","g"]}'
    )
    assert len(v.concerns) == 5


def test_parse_verdict_synthesises_concern_when_rejected_without_one() -> None:
    v = parse_verdict('{"approved": false, "concerns": [], "summary": "bad"}')
    assert v.approved is False
    assert v.concerns and "bad" in v.concerns[0]


def test_parse_verdict_defaults_to_approve_on_garbage() -> None:
    assert parse_verdict("").approved is True
    assert parse_verdict("not json at all").approved is True
    assert parse_verdict("{").approved is True


# ── capture_diff_for_witness ─────────────────────────────────────


def test_capture_diff_includes_post_content(tmp_path: Path) -> None:
    sub = tmp_path / "chimera" / "core"
    sub.mkdir(parents=True)
    (sub / "f.py").write_text("def foo():\n    return 1\n")
    blob = capture_diff_for_witness(
        ["chimera/core/f.py"], worktree=tmp_path,
    )
    assert "chimera/core/f.py" in blob
    assert "return 1" in blob


def test_capture_diff_truncates_at_budget(tmp_path: Path) -> None:
    big = "x = 1\n" * 20_000
    (tmp_path / "a.py").write_text(big)
    (tmp_path / "b.py").write_text("y = 2\n")
    blob = capture_diff_for_witness(
        ["a.py", "b.py"], worktree=tmp_path, max_bytes=2_000,
    )
    assert "truncated" in blob


def test_capture_diff_ignores_missing_files(tmp_path: Path) -> None:
    blob = capture_diff_for_witness(
        ["nonexistent.py"], worktree=tmp_path,
    )
    assert blob == ""


# ── witness_code_change (with stub provider) ─────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_witness_clean_diff_approved() -> None:
    provider = _StubProvider(
        '{"approved": true, "concerns": [], "summary": "looks fine"}'
    )
    verdict = _run(witness_code_change(
        task_text="add a docstring to foo",
        diff="=== chimera/x.py ===\n+def foo():\n+    \"\"\"x.\"\"\"\n+    return 1\n",
        paths=["chimera/x.py"],
        provider=provider,
    ))
    assert verdict.approved is True
    assert len(provider.calls) == 1
    # task text reached the witness
    assert "docstring" in provider.calls[0]["messages"][0].content


def test_witness_broken_return_rejected() -> None:
    provider = _StubProvider(
        '{"approved": false, '
        '"concerns": ["chimera/core/act.py: dangling `return ActResult(` interrupted by dedented statement near line 1524"], '
        '"summary": "structural defect"}'
    )
    broken = textwrap.dedent("""
        def execute():
            if condition:
                return ActResult(
            verdict = detect_degenerate_loop(history)
            return verdict
    """)
    verdict = _run(witness_code_change(
        task_text="wire detect_ping_pong into ACT loop",
        diff=f"=== chimera/core/act.py ===\n{broken}",
        paths=["chimera/core/act.py"],
        provider=provider,
    ))
    assert verdict.approved is False
    assert verdict.concerns
    assert "dangling" in verdict.concerns[0]


def test_witness_skipped_when_no_foundational_paths() -> None:
    # Caller is expected to gate on should_witness(); witness_code_change
    # itself also returns approved when paths is empty.
    provider = _StubProvider('{"approved": false, "concerns": ["x"]}')
    verdict = _run(witness_code_change(
        task_text="task", diff="", paths=[], provider=provider,
    ))
    assert verdict.approved is True
    assert provider.calls == []


def test_witness_provider_crash_defaults_to_approve() -> None:
    class _Boom(Provider):
        name = "boom"

        def stream(self, *a, **kw):  # type: ignore[override]
            async def _agen():
                if False:
                    yield  # pragma: no cover
                raise RuntimeError("network down")
            return _agen()

        async def complete_with_tools(self, *a, **kw):  # pragma: no cover
            raise NotImplementedError

    verdict = _run(witness_code_change(
        task_text="t",
        diff="=== chimera/x.py ===\nfoo\n",
        paths=["chimera/x.py"],
        provider=_Boom(),
    ))
    assert verdict.approved is True
    assert "error" in verdict.summary.lower() or "default" in verdict.summary.lower()


# ── Env config ───────────────────────────────────────────────────


def test_witness_enabled_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHIMERA_WITNESS_ENABLED", raising=False)
    assert witness_enabled() is True


def test_witness_enabled_off_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIMERA_WITNESS_ENABLED", "0")
    assert witness_enabled() is False


def test_witness_tier_default_sonnet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHIMERA_WITNESS_TIER", raising=False)
    assert witness_tier() == "sonnet"


def test_witness_tier_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIMERA_WITNESS_TIER", "opus")
    assert witness_tier() == "opus"


# ── Wiring: escalation / trust / remediation ─────────────────────


def test_witness_rejected_is_escalating_finish_reason() -> None:
    assert "witness_rejected" in ESCALATING_FINISH_REASONS


def test_witness_rejected_trust_delta_is_zero() -> None:
    # Same bucket as ungrounded_citation: 0 demote, three-strikes handles repeats.
    assert FINISH_REASON_TRUST_DELTAS["witness_rejected"] == 0


def test_witness_rejected_hint_without_detail_is_generic() -> None:
    hint = _witness_rejected_hint("task text", witness_concerns=None)
    assert "rejected" in hint.lower()
    assert "rewrite" in hint.lower()


def test_witness_rejected_hint_with_detail_names_concerns() -> None:
    concerns = [
        "chimera/core/act.py: dangling return",
        "tests/test_x.py: imports non-existent symbol foo",
    ]
    hint = _witness_rejected_hint("task", witness_concerns=concerns)
    assert "dangling return" in hint
    assert "non-existent symbol foo" in hint


def test_witness_rejected_hint_caps_at_three_concerns() -> None:
    concerns = [f"c{i}" for i in range(8)]
    hint = _witness_rejected_hint("task", witness_concerns=concerns)
    assert "c2" in hint
    assert "c3" not in hint


def test_derive_remediation_hint_dispatches_witness_rejected() -> None:
    hint = derive_remediation_hint("task", "witness_rejected")
    assert hint is not None
    assert "rejected" in hint.lower()
