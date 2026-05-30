"""v4.103 (ADR 0107): cross-provider witness panel for code review.

Covers panel composition (provider diversity + agent-once rule),
voting (unanimous default), concerns aggregation, diff-size handling
(no silent truncation; per-file chunking), and the v10 fixture replay
(broken Python from soak v10 must be flagged by every panel member).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

from chimera.core.witness import WitnessVerdict
from chimera.core.witness_panel import (
    PanelMember,
    aggregate_concerns,
    _is_charter_concern,
    build_witness_panel,
    diff_fits,
    panel_decision,
    panel_size,
    review_with_panel,
    split_by_file,
    voting_rule,
)
from chimera.providers.base import ChatChunk, ChatMessage, Provider
from chimera.providers.messages import ChatResponse, Message
from chimera.providers.tiers import Provider as ProviderKind


# ── Stub provider (records calls, yields canned reply) ──────────


class _StubProvider(Provider):
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
        self.calls.append({"model_id": model_id, "system": system})

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


# ── Config knobs ────────────────────────────────────────────────


def test_panel_size_defaults_to_three(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHIMERA_WITNESS_PANEL_SIZE", raising=False)
    assert panel_size() == 3


def test_panel_size_clamps_to_one_five(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIMERA_WITNESS_PANEL_SIZE", "99")
    assert panel_size() == 5
    monkeypatch.setenv("CHIMERA_WITNESS_PANEL_SIZE", "0")
    assert panel_size() == 1


def test_voting_rule_defaults_to_majority(monkeypatch: pytest.MonkeyPatch) -> None:
    # v44 R2: relaxed from unanimous — the build soaks showed a single
    # idiosyncratic dissent on a correct diff churned the soak. The charter
    # override (panel_decision) preserves the strict catch for security.
    monkeypatch.delenv("CHIMERA_WITNESS_VOTING", raising=False)
    assert voting_rule() == "majority"


def test_voting_rule_unanimous_still_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIMERA_WITNESS_VOTING", "unanimous")
    assert voting_rule() == "unanimous"


# ── Panel composition ──────────────────────────────────────────


def test_build_panel_prefers_other_providers_first() -> None:
    panel = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3,
    )
    assert len(panel) == 3
    # All three should be OpenRouter — v4.111 expanded the pool to 5
    # (4 OpenRouter + 1 Anthropic), so with size=3 and the agent on
    # Anthropic, the other-provider preference fills the whole panel
    # before the agent's own provider gets a slot.
    assert all(m.provider_kind == ProviderKind.OPENROUTER for m in panel)
    # Agent's own provider appears at most once (zero is fine).
    own = [m for m in panel if m.provider_kind == ProviderKind.ANTHROPIC]
    assert len(own) <= 1


def test_build_panel_skips_unavailable_provider() -> None:
    panel = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC},
        size=3,
    )
    # Only Anthropic configured → only one Anthropic member; the rest
    # of the default panel is OpenRouter and gets skipped.
    assert all(m.provider_kind == ProviderKind.ANTHROPIC for m in panel)
    assert len(panel) <= 1


def test_build_panel_seed_rotates_member_selection() -> None:
    """v4.111: pool=5, panel=3 → different seeds select different members.

    The pool has 4 OpenRouter members + 1 Anthropic. With panel_size=3
    and the agent on Anthropic, two distinct seeds must produce at
    least one differing label, otherwise the rotation is dead.
    """
    a = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3,
        seed=0,
    )
    b = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3,
        seed=7,
    )
    assert {m.label for m in a} != {m.label for m in b}, (
        f"rotation failed: seed=0 → {[m.label for m in a]}, "
        f"seed=7 → {[m.label for m in b]}"
    )


def test_build_panel_seed_is_deterministic() -> None:
    """Same seed → same panel (no hidden global state)."""
    a = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3, seed=42,
    )
    b = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3, seed=42,
    )
    assert [m.label for m in a] == [m.label for m in b]


def test_build_panel_no_seed_preserves_declaration_order() -> None:
    """When seed is None, ordering must match the v4.103 contract.

    Tests and fixtures (v10 replay, v13 charter) rely on the first
    three members being the historical default panel.
    """
    panel = build_witness_panel(
        ProviderKind.ANTHROPIC,
        available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
        size=3,
        # seed intentionally omitted
    )
    assert [m.label for m in panel[:2]] == [
        "openrouter:deepseek-v4-pro",
        "openrouter:gpt-5-pro",
    ]


def test_build_panel_seed_still_enforces_agent_once() -> None:
    """Rotation must not break the v4.103 agent-once rule."""
    for s in range(10):
        panel = build_witness_panel(
            ProviderKind.ANTHROPIC,
            available={ProviderKind.ANTHROPIC, ProviderKind.OPENROUTER},
            size=3, seed=s,
        )
        own = [m for m in panel if m.provider_kind == ProviderKind.ANTHROPIC]
        assert len(own) <= 1, (
            f"seed={s}: agent provider appears {len(own)} times"
        )


def test_build_panel_warns_when_single_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        panel = build_witness_panel(
            ProviderKind.ANTHROPIC,
            available={ProviderKind.ANTHROPIC},
            size=3,
            require_diversity=True,
        )
    assert len(panel) >= 1
    assert any("only 1 provider" in r.message for r in caplog.records)


# ── Voting ─────────────────────────────────────────────────────


def test_panel_decision_unanimous_all_approve() -> None:
    vs = [WitnessVerdict(approved=True) for _ in range(3)]
    assert panel_decision(vs, voting="unanimous") is True


def test_panel_decision_unanimous_one_dissent_rejects() -> None:
    vs = [
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=False, concerns=["bad"]),
        WitnessVerdict(approved=True),
    ]
    assert panel_decision(vs, voting="unanimous") is False


def test_panel_decision_majority_two_of_three_approves() -> None:
    vs = [
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=False, concerns=["bad"]),
    ]
    assert panel_decision(vs, voting="majority") is True


def test_panel_decision_empty_panel_approves() -> None:
    assert panel_decision([], voting="unanimous") is True


# ── v44 R2: asymmetric voting (charter override + majority default) ──

def test_majority_single_codequality_dissent_approves() -> None:
    # THE over-rejection fix: one model nitpicks a CORRECT diff; under the
    # majority default the panel still approves (2 of 3), no churn.
    vs = [
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=False, concerns=["possible off-by-one in the loop"]),
    ]
    assert panel_decision(vs, voting="majority") is True


def test_charter_concern_single_dissent_rejects_under_majority() -> None:
    # The high-value catch is PRESERVED: one model flags a charter/security
    # crossing → reject even though the other two approve (majority rule).
    vs = [
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=True),
        WitnessVerdict(
            approved=False,
            concerns=["crosses read-only-ish charter (shell.py): adds `rm` to RAW_ALLOWLIST"],
        ),
    ]
    assert panel_decision(vs, voting="majority") is False


def test_majority_two_codequality_dissents_reject() -> None:
    # A genuine signal (2 of 3 disapprove) still rejects under majority.
    vs = [
        WitnessVerdict(approved=True),
        WitnessVerdict(approved=False, concerns=["inverted condition"]),
        WitnessVerdict(approved=False, concerns=["swapped operands"]),
    ]
    assert panel_decision(vs, voting="majority") is False


def test_charter_override_applies_even_in_unanimous_mode() -> None:
    # The override is rule-independent: a charter dissent rejects under both.
    vs = [WitnessVerdict(approved=False, concerns=["expands the sandbox scope past the charter"])]
    assert panel_decision(vs, voting="unanimous") is False
    assert panel_decision(vs, voting="majority") is False


def test_is_charter_concern_detection() -> None:
    assert _is_charter_concern("adds write-capable rm to RAW_ALLOWLIST")
    assert _is_charter_concern("crosses the read-only charter boundary")
    assert _is_charter_concern("violates MUST NOT touch cli.py")
    assert not _is_charter_concern("possible off-by-one error")
    assert not _is_charter_concern("missing a docstring on the helper")


# ── Aggregation ────────────────────────────────────────────────


def test_aggregate_concerns_tags_with_label() -> None:
    labelled = [
        ("anthropic:sonnet", WitnessVerdict(
            approved=False, concerns=["Dangling open-paren on line 1524"],
        )),
        ("openrouter:deepseek-v4-pro", WitnessVerdict(
            approved=False, concerns=["Indentation discontinuity at 1525"],
        )),
    ]
    out = aggregate_concerns(labelled)
    assert any("[anthropic:sonnet]" in c for c in out)
    assert any("[openrouter:deepseek-v4-pro]" in c for c in out)


def test_aggregate_concerns_dedupes_similar() -> None:
    labelled = [
        ("a", WitnessVerdict(approved=False, concerns=["Same defect line 10"])),
        ("b", WitnessVerdict(approved=False, concerns=["Same defect line 10"])),
    ]
    out = aggregate_concerns(labelled)
    assert len(out) == 1


def test_aggregate_concerns_ignores_approving_witnesses() -> None:
    labelled = [
        ("a", WitnessVerdict(approved=True)),
        ("b", WitnessVerdict(approved=False, concerns=["real bug"])),
    ]
    out = aggregate_concerns(labelled)
    assert len(out) == 1
    assert "[b]" in out[0]


# ── Diff sizing ────────────────────────────────────────────────


def test_diff_fits_small_diff_all_members() -> None:
    panel = [
        PanelMember("a", ProviderKind.ANTHROPIC, "x", context_tokens=200_000),
        PanelMember("b", ProviderKind.OPENROUTER, "y", context_tokens=400_000),
    ]
    assert diff_fits("=== p ===\nshort\n", panel) is True


def test_diff_fits_oversize_triggers_chunking() -> None:
    # Build a diff just over the smallest member's window.
    panel = [
        PanelMember("tiny", ProviderKind.ANTHROPIC, "x", context_tokens=1_000),
        PanelMember("big", ProviderKind.OPENROUTER, "y", context_tokens=400_000),
    ]
    big_diff = "=== p ===\n" + ("X" * 10_000)
    assert diff_fits(big_diff, panel) is False


def test_split_by_file_preserves_headers() -> None:
    diff = (
        "=== a.py ===\n--- HEAD:a.py\n+++ working:a.py\nbody1\n"
        "=== b.py ===\n--- HEAD:b.py\n+++ working:b.py\nbody2\n"
    )
    chunks = split_by_file(diff)
    assert len(chunks) == 2
    assert chunks[0].startswith("=== a.py ===")
    assert chunks[1].startswith("=== b.py ===")


# ── End-to-end: review_with_panel ──────────────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_panel_unanimous_approve_does_not_fire() -> None:
    panel = [
        PanelMember("a", ProviderKind.ANTHROPIC, "m1"),
        PanelMember("b", ProviderKind.OPENROUTER, "m2"),
        PanelMember("c", ProviderKind.OPENROUTER, "m3"),
    ]
    approving_reply = '{"approved": true, "concerns": [], "summary": "lgtm"}'
    providers = {
        ProviderKind.ANTHROPIC: _StubProvider(approving_reply),
        ProviderKind.OPENROUTER: _StubProvider(approving_reply),
    }
    diff = "=== chimera/core/act.py ===\n--- HEAD\n+++ working\nok\n"
    labelled = asyncio.new_event_loop().run_until_complete(
        review_with_panel(
            "do the thing", diff, ["chimera/core/act.py"],
            panel, providers.get,
        )
    )
    assert len(labelled) == 3
    assert panel_decision(v for _, v in labelled) is True


def test_panel_one_dissent_triggers_witness_rejected() -> None:
    panel = [
        PanelMember("a", ProviderKind.ANTHROPIC, "m1"),
        PanelMember("b", ProviderKind.OPENROUTER, "m2"),
    ]
    # Anthropic approves; OpenRouter rejects.
    providers = {
        ProviderKind.ANTHROPIC: _StubProvider(
            '{"approved": true, "concerns": [], "summary": "ok"}'
        ),
        ProviderKind.OPENROUTER: _StubProvider(
            '{"approved": false, "concerns": ["dangling open paren line 1524"], "summary": "bad"}'
        ),
    }
    diff = "=== chimera/core/act.py ===\n--- HEAD\n+++ working\nbroken\n"
    labelled = asyncio.new_event_loop().run_until_complete(
        review_with_panel(
            "fix it", diff, ["chimera/core/act.py"],
            panel, providers.get,
        )
    )
    assert panel_decision(v for _, v in labelled) is False
    concerns = aggregate_concerns(labelled)
    assert any("[b]" in c and "dangling" in c for c in concerns)


def test_panel_unavailable_provider_defaults_to_approve() -> None:
    panel = [
        PanelMember("ghost", ProviderKind.OPENROUTER, "m1"),
    ]
    labelled = asyncio.new_event_loop().run_until_complete(
        review_with_panel(
            "anything", "=== x ===\nbody\n", ["chimera/core/x.py"],
            panel, lambda kind: None,
        )
    )
    assert len(labelled) == 1
    assert labelled[0][1].approved is True


def test_panel_oversize_diff_splits_and_does_not_truncate() -> None:
    # tiny context forces splitting; we verify the stub provider was
    # called once PER chunk PER member rather than once with a
    # truncated diff.
    panel = [PanelMember("tiny", ProviderKind.ANTHROPIC, "m1", context_tokens=600)]
    stub = _StubProvider('{"approved": true, "concerns": [], "summary": ""}')
    diff = (
        "=== a.py ===\n--- HEAD\n+++ working\n" + ("A" * 1500) + "\n"
        "=== b.py ===\n--- HEAD\n+++ working\n" + ("B" * 1500) + "\n"
    )
    asyncio.new_event_loop().run_until_complete(
        review_with_panel(
            "task", diff, ["a.py", "b.py"],
            panel, lambda kind: stub,
        )
    )
    # 2 chunks, 1 member → 2 calls. If truncation happened silently
    # we'd see only 1.
    assert len(stub.calls) == 2


# ── v10 fixture replay ─────────────────────────────────────────


V10_BROKEN_DIFF = """=== chimera/core/act.py ===
--- HEAD:chimera/core/act.py
+++ working:chimera/core/act.py
# PRE (0 bytes):

# POST (… bytes):
            if verdict is LoopVerdict.OK:
                verdict = detect_ping_pong(history)
                return ActResult(
            verdict = detect_degenerate_loop(history)
            if verdict is LoopVerdict.ABORT:
                    task_text=task_text,
                    rounds=round_idx + 1,
                    completed=False,
"""


def test_v10_fixture_all_panel_members_must_flag() -> None:
    """Soak v10 reference fixture: every default-panel member should reject.

    If any member approves the dangling ``ActResult(`` block, the
    panel composition is too weak — that's the signal v4.103 was
    built to surface.
    """
    panel = [
        PanelMember("anthropic:sonnet", ProviderKind.ANTHROPIC, "m1"),
        PanelMember("openrouter:deepseek-v4-pro", ProviderKind.OPENROUTER, "m2"),
        PanelMember("openrouter:gpt-5-pro", ProviderKind.OPENROUTER, "m3"),
    ]
    # All three witnesses (simulated) flag the structural defect.
    rejection = (
        '{"approved": false, '
        '"concerns": ["Dangling open-paren on `ActResult(` at line 1524; '
        'dedented `verdict = detect_degenerate_loop(...)` interrupts the call"], '
        '"summary": "structurally invalid return block"}'
    )
    providers = {
        ProviderKind.ANTHROPIC: _StubProvider(rejection),
        ProviderKind.OPENROUTER: _StubProvider(rejection),
    }
    labelled = asyncio.new_event_loop().run_until_complete(
        review_with_panel(
            "wire detect_degenerate_loop into the act loop",
            V10_BROKEN_DIFF,
            ["chimera/core/act.py"],
            panel, providers.get,
        )
    )
    assert len(labelled) == 3
    assert all(not v.approved for _, v in labelled), (
        "v10 fixture must be unanimously rejected; if any panel "
        "member approves, the panel composition is too weak"
    )
    assert panel_decision(v for _, v in labelled) is False
    concerns = aggregate_concerns(labelled)
    assert len(concerns) >= 1
    assert any("ActResult" in c for c in concerns)
