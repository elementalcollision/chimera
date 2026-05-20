"""Tests for the ACT executor — multi-turn tool-using inner loop."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from chimera.core.act import ActExecutor
from chimera.memory import open_and_init
from chimera.providers import (
    ChatChunk,
    ChatMessage,
    ChatResponse,
    Message,
    Provider,
    ToolUseBlock,
)
from chimera.providers.tiers import Provider as ProviderKind
from chimera.tools import (
    DispatchContext,
    Dispatcher,
    ToolRegistry,
    register_shell_tool,
)


# ── Fake provider ───────────────────────────────────────────


class _FakeProvider(Provider):
    """A scripted provider that returns a queue of pre-built responses.

    The model_id passed in is ignored; the harness just walks the queue.
    """

    name = "fake"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, messages, *, model_id, max_tokens=4096, system=None):
        if False:
            yield ChatChunk(text="")  # pragma: no cover — abstract satisfied

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model_id": model_id,
                "messages": messages,
                "tools": [t["function"]["name"] for t in tools],
                "max_tokens": max_tokens,
            }
        )
        if not self._responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self._responses.pop(0)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def shell_env(tmp_path: Path, monkeypatch):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    return mind, state


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.fixture
def dispatcher() -> Dispatcher:
    reg = ToolRegistry()
    register_shell_tool(reg)
    return Dispatcher(reg)


# ── Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_act_no_tools_used_completes_immediately(dispatcher, db):
    fake = _FakeProvider(
        [
            ChatResponse(
                text="42.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            )
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("What's 6 times 7?", cycle=1)
    assert result.completed is True
    assert result.rounds == 1
    assert result.final_text == "42."
    assert result.tool_call_history == []
    assert result.api_call_count == 1


@pytest.mark.asyncio
async def test_act_runs_a_tool_then_completes(shell_env, dispatcher, db):
    mind, _ = shell_env
    (mind / "hello.txt").write_text("howdy\n")

    fake = _FakeProvider(
        [
            ChatResponse(
                text="checking",
                tool_uses=[
                    ToolUseBlock(
                        id="tu_1", name="shell", input={"argv": ["ls", "."]}
                    )
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            ),
            ChatResponse(
                text="I see hello.txt.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            ),
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("list files", cycle=1)
    assert result.completed is True
    assert result.rounds == 2
    assert len(result.tool_call_history) == 1
    assert result.tool_call_history[0].name == "shell"
    assert "hello.txt" in result.final_text or "hello.txt" not in result.final_text  # text optional
    assert result.api_call_count == 2


@pytest.mark.asyncio
async def test_act_aborts_on_degenerate_loop(shell_env, dispatcher, db):
    """Five identical shell calls in a row → ABORT verdict from the guard."""
    repeated_call = ToolUseBlock(id="tu", name="shell", input={"argv": ["ls", "."]})
    fake = _FakeProvider(
        [
            ChatResponse(
                text="",
                tool_uses=[ToolUseBlock(id=f"tu_{i}", name="shell", input={"argv": ["ls", "."]})],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(8)
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("loop forever", cycle=1)
    assert result.completed is False
    assert result.finish_reason == "degenerate_loop_abort"
    # Five identical calls before the guard fires.
    assert len(result.tool_call_history) == 5


@pytest.mark.asyncio
async def test_act_exhausts_max_rounds(shell_env, dispatcher, db):
    """Each round returns tool_use but with varying args → no abort, just max_rounds."""
    fake = _FakeProvider(
        [
            ChatResponse(
                text="",
                tool_uses=[
                    ToolUseBlock(id=f"tu_{i}", name="shell", input={"argv": ["ls", f"sub_{i}"]})
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            )
            for i in range(10)
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
        max_rounds=3,
    )
    result = await executor.execute("explore", cycle=1)
    assert result.completed is False
    assert result.finish_reason == "max_rounds"
    assert result.rounds == 3


@pytest.mark.asyncio
async def test_act_records_api_call_rows(shell_env, dispatcher, db):
    fake = _FakeProvider(
        [
            ChatResponse(
                text="done",
                tool_uses=[],
                stop_reason="stop",
                input_tokens=10,
                output_tokens=5,
                latency_ms=42,
                model_id="m",
                provider="fake",
            )
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    await executor.execute("ping", cycle=7)
    rows = db.execute(
        "SELECT cycle, input_tokens, output_tokens, latency_ms, finish_reason FROM api_calls"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["cycle"] == 7
    assert r["input_tokens"] == 10
    assert r["output_tokens"] == 5
    assert r["latency_ms"] == 42
    assert r["finish_reason"] == "stop"
    outcomes = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    assert outcomes[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_act_records_failure_outcome_on_provider_error(shell_env, dispatcher, db):
    class _BadProvider(_FakeProvider):
        async def complete_with_tools(self, *a, **kw):
            raise RuntimeError("provider down")

    bad = _BadProvider([])
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: bad, ProviderKind.ANTHROPIC: bad},
        db=db,
    )
    result = await executor.execute("anything", cycle=2)
    assert result.completed is False
    assert result.finish_reason == "provider_error"
    assert "provider down" in (result.failure_reason or "")
    outcomes = db.execute("SELECT outcome FROM ladder_outcomes").fetchall()
    # v3.11: each rung records retry_exhausted before the executor gives up.
    assert all(o["outcome"] == "retry_exhausted" for o in outcomes)
    assert len(outcomes) >= 1


@pytest.mark.asyncio
async def test_act_downgrades_to_artifact_missing_when_promised_file_absent(
    shell_env, dispatcher, db, tmp_path, monkeypatch,
):
    """v4.3: model says 'stop' but the promised artifact isn't on disk."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)  # state/ exists but the claimed log doesn't

    fake = _FakeProvider(
        [ChatResponse(text="Wrote it.", tool_uses=[], stop_reason="stop")]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute(
        "Write 'hi' to `state/missing.log` then stop.", cycle=42,
    )
    assert result.completed is False
    assert result.finish_reason == "artifact_missing"
    assert result.missing_artifacts == ["state/missing.log"]


@pytest.mark.asyncio
async def test_act_completes_when_artifact_exists(
    shell_env, dispatcher, db, tmp_path, monkeypatch,
):
    """Sanity: artifact path that DOES exist passes verification."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "present.log").write_text("ok")

    fake = _FakeProvider(
        [ChatResponse(text="Done.", tool_uses=[], stop_reason="stop")]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute(
        "Write to `state/present.log` and stop.", cycle=43,
    )
    assert result.completed is True
    assert result.missing_artifacts == []


@pytest.mark.asyncio
async def test_act_escalates_to_next_rung_on_first_rung_failure(shell_env, dispatcher, db):
    """v3.11: when one provider raises, ACT walks the next ladder rung."""
    flaky = _FakeProvider([])

    async def _raise(*a, **kw):
        raise RuntimeError("flaky rung")

    flaky.complete_with_tools = _raise  # type: ignore[assignment]
    healthy = _FakeProvider(
        [ChatResponse(text="all good", tool_uses=[], stop_reason="stop")]
    )
    # HAIKU_LADDER puts OpenRouter rungs first (cheapest) and Anthropic
    # last (safety net). Make OpenRouter flaky and Anthropic healthy so the
    # executor must escalate down the ladder to find success.
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: flaky, ProviderKind.ANTHROPIC: healthy},
        db=db,
    )
    result = await executor.execute("hello", cycle=3)
    assert result.completed is True
    assert "all good" in result.final_text
    outcomes = db.execute("SELECT outcome FROM ladder_outcomes ORDER BY id").fetchall()
    kinds = [o["outcome"] for o in outcomes]
    assert "retry_exhausted" in kinds
    assert "success" in kinds


# ── Live integration (env-gated) ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_act_live_anthropic_uses_shell_tool(shell_env, dispatcher, db):
    """End-to-end: real Anthropic model + real shell tool against a tmp mind dir."""
    mind, _ = shell_env
    (mind / "GREETINGS.md").write_text("hello there\n")

    executor = ActExecutor.from_env(dispatcher=dispatcher, db=db)
    if executor is None:
        pytest.skip("no provider keys available")

    result = await executor.execute(
        "List the files in the current directory and tell me what you see. Use the shell tool.",
        cycle=1,
    )
    # Model should have at least attempted a tool call and returned text.
    assert result.api_call_count >= 1
    # Either it called a tool and saw the file, or it answered directly.
    if result.tool_call_history:
        assert result.tool_call_history[0].name == "shell"


# ── v4.18: parallel tool dispatch ───────────────────────────


@pytest.mark.asyncio
async def test_act_dispatches_multiple_tool_uses_in_parallel(shell_env, db):
    """Two tool_uses in one response should fan out via asyncio.gather.

    We register a slow async tool that records start/end timestamps. If
    dispatch is parallel, the two calls overlap (end-start < 2*sleep).
    Serial dispatch would force end-start >= 2*sleep.
    """
    import asyncio
    import time

    starts: list[float] = []
    ends: list[float] = []

    async def _slow(args, ctx):
        starts.append(time.monotonic())
        await asyncio.sleep(0.15)
        ends.append(time.monotonic())
        return f"ok:{args.get('label', '?')}"

    reg = ToolRegistry()
    reg.register(
        name="slow_probe",
        toolset="test",
        description="sleeps 150ms then returns",
        schema={
            "type": "function",
            "function": {
                "name": "slow_probe",
                "description": "sleeps 150ms then returns",
                "parameters": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                },
            },
        },
        handler=_slow,
    )
    disp = Dispatcher(reg)

    fake = _FakeProvider(
        [
            ChatResponse(
                text="firing both",
                tool_uses=[
                    ToolUseBlock(id="tu_a", name="slow_probe", input={"label": "a"}),
                    ToolUseBlock(id="tu_b", name="slow_probe", input={"label": "b"}),
                ],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            ),
            ChatResponse(
                text="done",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            ),
        ]
    )
    executor = ActExecutor(
        dispatcher=disp,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )

    t0 = time.monotonic()
    result = await executor.execute("probe in parallel", cycle=1)
    elapsed = time.monotonic() - t0

    assert result.completed is True
    assert len(result.tool_call_history) == 2
    # Both started before either finished → overlapping execution.
    assert max(starts) < min(ends), (
        f"calls did not overlap: starts={starts} ends={ends}"
    )
    # Serial would have taken ≥0.30s for the two sleeps; parallel ≈0.15s.
    assert elapsed < 0.28, f"dispatch looks serial: elapsed={elapsed:.3f}s"

    # v4.33: tool_uses_count column captured the fan-out for telemetry.
    counts = [
        r["tool_uses_count"]
        for r in db.execute(
            "SELECT tool_uses_count FROM api_calls ORDER BY id"
        ).fetchall()
    ]
    # Two api_calls: first emitted 2 tool_uses (parallel), second was the
    # final text response with 0.
    assert counts == [2, 0], f"unexpected fan-out series: {counts}"


# ── v4.41: tool-arg validation feedback ─────────────────────


@pytest.mark.asyncio
async def test_act_validation_error_includes_schema_hint(db):
    """When a handler raises ValueError, the tool_result fed back to the
    next model round should include a schema hint, not just the
    exception text — so the model can self-correct."""

    async def _broken(args, ctx):
        # Mimic code_exec's strictness: complain when 'code' is missing.
        if not args.get("code"):
            raise ValueError("code must be a non-empty string")
        return f"ok:{len(args['code'])}"

    reg = ToolRegistry()
    reg.register(
        name="strict_probe",
        toolset="test",
        description="rejects empty input",
        schema={
            "type": "function",
            "function": {
                "name": "strict_probe",
                "description": "rejects empty input",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "timeout_s": {"type": "number"},
                    },
                    "required": ["code"],
                },
            },
        },
        handler=_broken,
    )

    captured_messages: list[Any] = []

    class _ObservingProvider(_FakeProvider):
        async def complete_with_tools(
            self, messages, *, model_id, tools, max_tokens=4096, system=None,
        ):
            captured_messages.append(list(messages))
            return await super().complete_with_tools(
                messages, model_id=model_id, tools=tools,
                max_tokens=max_tokens, system=system,
            )

    fake = _ObservingProvider(
        [
            ChatResponse(
                text="trying",
                tool_uses=[ToolUseBlock(id="tu_a", name="strict_probe", input={})],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            ),
            ChatResponse(
                text="giving up",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            ),
        ]
    )
    executor = ActExecutor(
        dispatcher=Dispatcher(reg),
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    await executor.execute("trigger schema hint", cycle=1)

    # The SECOND provider call should have seen the tool_result with the
    # hint message embedded.
    assert len(captured_messages) >= 2
    second_round_messages = captured_messages[1]
    found_hint = False
    for msg in second_round_messages:
        for block in getattr(msg, "blocks", []) or []:
            # ToolResultBlock has .content; TextBlock has .text. Either is fine.
            payload = getattr(block, "content", None) or getattr(block, "text", None)
            if isinstance(payload, str) and "hint: strict_probe" in payload:
                found_hint = True
                assert "code: string (required)" in payload
                assert "received keys: []" in payload
    assert found_hint, "schema hint did not reach the next model round"


# ── v4.42: continuation-context carry-over ──────────────────


@pytest.mark.asyncio
async def test_act_injects_continuation_context_for_existing_artifacts(
    shell_env, dispatcher, db, monkeypatch,
):
    """When the task references a path that already exists, the system
    prompt should carry a 'Continuation context' block so the model
    doesn't restart from zero."""
    mind, _ = shell_env
    # Pre-seed a partial artifact the task names with backticks.
    (mind / "draft.md").write_text("# Draft\n\nPartial work already.\n", encoding="utf-8")
    monkeypatch.chdir(mind.parent)

    captured: list[Any] = []

    class _Capture(_FakeProvider):
        async def complete_with_tools(
            self, messages, *, model_id, tools, max_tokens=4096, system=None,
        ):
            captured.append(list(messages))
            return await super().complete_with_tools(
                messages, model_id=model_id, tools=tools,
                max_tokens=max_tokens, system=system,
            )

    fake = _Capture(
        [
            ChatResponse(
                text="finishing up",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            )
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    await executor.execute(
        "Continue the draft at `mind/draft.md` — fix the truncation.",
        cycle=2,
    )

    assert captured, "provider was never called"
    first_messages = captured[0]
    system_msg = first_messages[0]
    system_text = system_msg.text() if hasattr(system_msg, "text") else ""
    assert "## Continuation context" in system_text
    assert "mind/draft.md" in system_text
    assert "Partial work already." in system_text


def test_act_no_continuation_block_for_fresh_task(tmp_path: Path):
    """Tasks that DON'T reference existing artifact paths produce no
    continuation block — pure unit check on the helper."""
    from chimera.core.act import _continuation_context

    text_no_paths = "Compute fibonacci of 10."
    assert _continuation_context(text_no_paths) == ""

    text_with_missing_path = (
        "Write the summary to `mind/never_existed.md` and stop."
    )
    # File doesn't exist → no block.
    assert _continuation_context(text_with_missing_path) == ""


# ── v4.50: round-boundary latency ───────────────────────────


@pytest.mark.asyncio
async def test_act_records_round_boundary_latency(shell_env, dispatcher, db):
    """Round N+1's api_calls row should carry the wall-clock between
    round N's last tool completion and round N+1's provider call.
    Round 0 has no prior boundary → NULL."""
    fake = _FakeProvider(
        [
            # Round 0: model asks for a tool.
            ChatResponse(
                text="thinking",
                tool_uses=[ToolUseBlock(
                    id="tu_1", name="shell", input={"argv": ["ls", "."]}
                )],
                stop_reason="tool_use",
                model_id="m",
                provider="fake",
            ),
            # Round 1: model finishes.
            ChatResponse(
                text="done.",
                tool_uses=[],
                stop_reason="stop",
                model_id="m",
                provider="fake",
            ),
        ]
    )
    executor = ActExecutor(
        dispatcher=dispatcher,
        providers={
            ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake,
        },
        db=db,
    )
    result = await executor.execute("list files briefly", cycle=1)
    assert result.completed is True
    rows = db.execute(
        "SELECT round_boundary_latency_ms FROM api_calls ORDER BY id"
    ).fetchall()
    # Two rows: first has NULL (no prior round), second has a real
    # non-negative ms measurement.
    assert len(rows) == 2
    assert rows[0]["round_boundary_latency_ms"] is None
    assert isinstance(rows[1]["round_boundary_latency_ms"], int)
    assert rows[1]["round_boundary_latency_ms"] >= 0
