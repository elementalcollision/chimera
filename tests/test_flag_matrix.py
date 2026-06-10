"""Flag-combination matrix over the ACT hot path (ADR 0176).

The CHIMERA_FANOUT_BUDGET interaction bug (zero API calls when combined
with other routing/entropy flags) escaped to live runs because every flag
was tested alone and no flags were tested together. This module closes
that class: it exercises every single flag, every PAIR of high-impact
flags, and the all-on envelope against one invariant —

    ACT with a scripted provider still executes: >= 1 provider call is
    made, the task completes, and parallel tool fan-out produces results.

The flag list lives in chimera.config.HIGH_IMPACT_FLAGS so new hot-path
flags are added to the matrix by declaring them there (the registry
completeness test will point you at it).
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest

from chimera.config import HIGH_IMPACT_FLAGS
from chimera.core.act import ActExecutor
from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Message, Provider, ToolUseBlock
from chimera.providers.tiers import Provider as ProviderKind
from chimera.tools import Dispatcher, ToolRegistry, register_shell_tool

# CHIMERA_FANOUT_MAX_WIDTH is a parameter of CHIMERA_FANOUT_BUDGET, not an
# independent feature — the matrix axes are the togglers; WIDTH rides along
# whenever FANOUT_BUDGET is on.
_AXES: list[str] = [n for n in HIGH_IMPACT_FLAGS if n != "CHIMERA_FANOUT_MAX_WIDTH"]


def _env_for(flags: tuple[str, ...]) -> dict[str, str]:
    env = {name: HIGH_IMPACT_FLAGS[name] for name in flags}
    if "CHIMERA_FANOUT_BUDGET" in env:
        env["CHIMERA_FANOUT_MAX_WIDTH"] = HIGH_IMPACT_FLAGS["CHIMERA_FANOUT_MAX_WIDTH"]
    return env


_SINGLES = [(name,) for name in _AXES]
_PAIRS = list(itertools.combinations(_AXES, 2))
_ALL_ON = [tuple(_AXES)]
MATRIX: list[tuple[str, ...]] = _SINGLES + _PAIRS + _ALL_ON


class _FakeProvider(Provider):
    """Scripted provider (same shape as tests/test_act.py)."""

    name = "fake"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, messages, *, model_id, max_tokens=4096, system=None):
        if False:
            yield ChatChunk(text="")  # pragma: no cover

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        model_id: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> ChatResponse:
        self.calls.append({"model_id": model_id})
        if not self._responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _isolate_from_git_state(monkeypatch):
    """Same isolation as tests/test_act.py (ADR 0122): the v4.115/v4.118
    detectors shell out to real git and would leak branch state in here."""
    from chimera.core import act as _act

    monkeypatch.setattr(_act, "check_commit_message_diff_drift", lambda *a, **kw: [])
    monkeypatch.setattr(_act, "check_provenance_claim_valid", lambda *a, **kw: [])


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


def _scripted_provider() -> _FakeProvider:
    """Round 1 fans out THREE distinct parallel tool calls (so a fan-out
    width of 2 must trim + defer + re-issue), rounds 2-3 absorb any
    deferred re-issues, final round stops clean. Generous queue: flag
    combinations may legitimately take different numbers of rounds, and
    leftover scripted responses are fine — running OUT is the failure."""
    fanout = ChatResponse(
        text="",
        tool_uses=[
            ToolUseBlock(id="tu_1", name="shell", input={"argv": ["ls", "."]}),
            ToolUseBlock(id="tu_2", name="shell", input={"argv": ["ls", "-a"]}),
            ToolUseBlock(id="tu_3", name="shell", input={"argv": ["pwd"]}),
        ],
        stop_reason="tool_use",
        model_id="m",
        provider="fake",
    )
    reissue = ChatResponse(
        text="",
        tool_uses=[
            ToolUseBlock(id="tu_4", name="shell", input={"argv": ["pwd"]}),
        ],
        stop_reason="tool_use",
        model_id="m",
        provider="fake",
    )
    done = ChatResponse(
        text="Done: listed the working directory.",
        tool_uses=[],
        stop_reason="stop",
        model_id="m",
        provider="fake",
    )
    return _FakeProvider([fanout, reissue, done, done, done])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flags", MATRIX, ids=["+".join(f.removeprefix("CHIMERA_") for f in c) for c in MATRIX]
)
async def test_act_executes_under_flag_combination(flags, shell_env, db, monkeypatch):
    for name, value in _env_for(flags).items():
        monkeypatch.setenv(name, value)

    reg = ToolRegistry()
    register_shell_tool(reg)
    fake = _scripted_provider()
    executor = ActExecutor(
        dispatcher=Dispatcher(reg),
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("List the working directory contents", cycle=1)

    # THE invariant — the FANOUT_BUDGET bug class is exactly this going to 0.
    assert len(fake.calls) >= 1, (
        f"zero provider calls under flags {flags} — flag-interaction "
        f"regression of the CHIMERA_FANOUT_BUDGET class"
    )
    assert result is not None
    assert result.completed is True, (
        f"task failed to complete under flags {flags}: "
        f"finish_reason={result.finish_reason!r}"
    )
    assert result.tool_call_history, f"no tools dispatched under flags {flags}"


@pytest.mark.asyncio
async def test_act_baseline_no_flags(shell_env, db):
    """Anchor cell: the same scenario with NO flags set must pass, so a
    matrix failure is attributable to the flags and not the harness."""
    reg = ToolRegistry()
    register_shell_tool(reg)
    fake = _scripted_provider()
    executor = ActExecutor(
        dispatcher=Dispatcher(reg),
        providers={ProviderKind.OPENROUTER: fake, ProviderKind.ANTHROPIC: fake},
        db=db,
    )
    result = await executor.execute("List the working directory contents", cycle=1)
    assert len(fake.calls) >= 1
    assert result.completed is True
