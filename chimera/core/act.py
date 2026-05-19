"""ACT executor — the multi-turn tool-using agent loop.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)" + ADR 0001
§"Tool registry" + §"Tool dispatch policy":

For each open task:
  1. Build messages: a Chimera-flavored system prompt + the task text.
  2. Get the tools schema visible to the current dispatch context.
  3. Pick a rung from the tier ladder (cheapest-first by default).
  4. Call ``provider.complete_with_tools()``.
  5. If the model emitted tool_uses, run them through the Dispatcher
     (which enforces the OpenClaw-style policy pipeline) and feed
     results back.
  6. Repeat up to ``max_rounds``.
  7. Apply ACT guards: ``normalize_tool_input`` on every call,
     ``detect_degenerate_loop`` on the running history.

The executor records ``api_calls`` and ``ladder_outcomes`` rows so the
adaptive routing policy (a later sprint) has data to work with.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..memory import record_api_call, record_ladder_outcome
from ..prompts import build_system_prompt
from ..providers import (
    AnthropicProvider,
    Message,
    OpenRouterProvider,
    Provider,
    ToolResultBlock,
)
from ..providers.tiers import LadderRung
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import select_rung
from ..tools import (
    DispatchContext,
    Dispatcher,
    LoopVerdict,
    ToolCall,
    ToolDenied,
    detect_degenerate_loop,
    extract_target_paths,
    normalize_tool_input,
)

logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_PROMPT_EXTRA = (
    "Task-specific guidance:\n"
    "- Prefer the shell tool for read-only inspection of /mind and /state.\n"
    "- Use http_fetch / web_search when the task points outside the container.\n"
    "- Use code_exec for computation, not shell `bash -c`.\n"
    "- When you have enough to answer, respond and stop."
)


@dataclass
class ActResult:
    task_text: str
    completed: bool
    rounds: int
    finish_reason: str
    write_targets: list[str] = field(default_factory=list)
    tool_call_history: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    failure_reason: str | None = None
    api_call_count: int = 0


class ActExecutor:
    """Runs the tool-using inner loop for a single task."""

    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        tier: str = "haiku",
        max_rounds: int = 8,
        max_tokens: int = 2048,
        system_prompt_extra: str = DEFAULT_SYSTEM_PROMPT_EXTRA,
    ) -> None:
        self._dispatcher = dispatcher
        self._providers = providers
        self._db = db
        self._tier = tier
        self._max_rounds = max_rounds
        self._max_tokens = max_tokens
        self._system_prompt_extra = system_prompt_extra

    def _build_system_prompt(self, *, cycle: int) -> str:
        return build_system_prompt(
            self._db,
            cycle=max(cycle, 0),
            extra=self._system_prompt_extra,
        )

    @classmethod
    def from_env(
        cls,
        *,
        dispatcher: Dispatcher | None,
        db: sqlite3.Connection,
        tier: str = "haiku",
    ) -> ActExecutor | None:
        """Construct using whichever provider env keys are available.

        Returns ``None`` if neither key is set — caller should skip ACT.

        ``dispatcher`` may be None for helpers that only need provider
        access (e.g. the skills CLI uses this just to get .providers).
        """
        providers: dict[ProviderKind, Provider] = {}
        try:
            providers[ProviderKind.ANTHROPIC] = AnthropicProvider()
        except RuntimeError:
            pass
        try:
            providers[ProviderKind.OPENROUTER] = OpenRouterProvider()
        except RuntimeError:
            pass
        if not providers:
            return None
        if dispatcher is None:
            # v2.5: default to PeerAwareDispatcher so cross-agent trust gating
            # is on by default for any caller that doesn't supply its own.
            from ..a2a import PeerAwareDispatcher
            dispatcher = PeerAwareDispatcher()  # uses default_registry
        return cls(dispatcher=dispatcher, providers=providers, db=db, tier=tier)

    @property
    def providers(self) -> dict[ProviderKind, Provider]:
        return self._providers

    # ── execution ──────────────────────────────────────────

    def _pick_rung(self, *, requires_tools: bool) -> LadderRung:
        return select_rung(self._tier, requires_tools=requires_tools)

    def _provider_for(self, rung: LadderRung) -> Provider | None:
        return self._providers.get(rung.config.provider)

    def _model_id_for(self, rung: LadderRung) -> str:
        if rung.config.provider is ProviderKind.ANTHROPIC:
            return rung.config.model_id
        return rung.config.openrouter_model_id

    async def execute(
        self,
        task_text: str,
        *,
        cycle: int,
        context: DispatchContext | None = None,
    ) -> ActResult:
        ctx = context or DispatchContext()
        messages: list[Message] = [
            Message.system(self._build_system_prompt(cycle=cycle)),
            Message.user(task_text),
        ]
        tools_schema = self._dispatcher.registry.schemas()
        history: list[ToolCall] = []
        write_targets: list[str] = []
        api_call_count = 0
        final_text = ""
        stop_reason = ""

        rung = self._pick_rung(requires_tools=True)
        provider = self._provider_for(rung)
        if provider is None:
            return ActResult(
                task_text=task_text,
                completed=False,
                rounds=0,
                finish_reason="provider_unavailable",
                failure_reason=f"no provider for {rung.config.provider}",
            )

        for round_idx in range(self._max_rounds):
            try:
                response = await provider.complete_with_tools(
                    messages=messages,
                    model_id=self._model_id_for(rung),
                    tools=tools_schema,
                    max_tokens=self._max_tokens,
                )
            except Exception as exc:
                record_api_call(
                    self._db,
                    cycle=cycle,
                    provider=provider.name,
                    model_id=self._model_id_for(rung),
                    error=str(exc),
                )
                record_ladder_outcome(
                    self._db,
                    cycle=cycle,
                    tier=self._tier,
                    rung_model_id=rung.label,
                    outcome="non_retriable",
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="provider_error",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )

            api_call_count += 1
            record_api_call(
                self._db,
                cycle=cycle,
                provider=provider.name,
                model_id=response.model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
                finish_reason=response.stop_reason,
            )
            record_ladder_outcome(
                self._db,
                cycle=cycle,
                tier=self._tier,
                rung_model_id=rung.label,
                outcome="success",
            )

            final_text = response.text
            stop_reason = response.stop_reason

            # No tools → done.
            if not response.tool_uses or response.stop_reason in ("stop", "length"):
                return ActResult(
                    task_text=task_text,
                    completed=response.stop_reason == "stop",
                    rounds=round_idx + 1,
                    finish_reason=response.stop_reason,
                    write_targets=write_targets,
                    tool_call_history=history,
                    final_text=final_text,
                    api_call_count=api_call_count,
                )

            # Append assistant turn with the model's tool_use blocks.
            messages.append(Message.assistant(response.text, response.tool_uses))

            # Dispatch each tool call; build the tool_result turn.
            tool_results: list[ToolResultBlock] = []
            for tu in response.tool_uses:
                args = normalize_tool_input(tu.input)
                call = ToolCall(name=tu.name, args=args)
                history.append(call)

                verdict = detect_degenerate_loop(history)
                if verdict is LoopVerdict.ABORT:
                    return ActResult(
                        task_text=task_text,
                        completed=False,
                        rounds=round_idx + 1,
                        finish_reason="degenerate_loop_abort",
                        write_targets=write_targets,
                        tool_call_history=history,
                        final_text=final_text,
                        failure_reason="aborted after repeated identical tool calls",
                        api_call_count=api_call_count,
                    )

                try:
                    output = await self._dispatcher.dispatch(tu.name, args, ctx)
                    tool_results.append(
                        ToolResultBlock(tool_use_id=tu.id, content=output, is_error=False)
                    )
                except ToolDenied as exc:
                    tool_results.append(
                        ToolResultBlock(
                            tool_use_id=tu.id, content=f"tool denied: {exc}", is_error=True
                        )
                    )
                except Exception as exc:
                    logger.exception("tool dispatch failed: %s", tu.name)
                    tool_results.append(
                        ToolResultBlock(
                            tool_use_id=tu.id, content=f"error: {exc}", is_error=True
                        )
                    )

            # Track write_targets the agent may have produced. The shell tool
            # doesn't write, but future write tools will populate this via the
            # path-extraction heuristic on tool args.
            for call in history[-len(response.tool_uses) :]:
                for path in extract_target_paths(" ".join(map(str, call.args.values()))):
                    if path not in write_targets:
                        write_targets.append(path)

            messages.append(Message.tool_results(tool_results))

        return ActResult(
            task_text=task_text,
            completed=False,
            rounds=self._max_rounds,
            finish_reason="max_rounds",
            write_targets=write_targets,
            tool_call_history=history,
            final_text=final_text,
            failure_reason="exhausted max rounds without final stop",
            api_call_count=api_call_count,
        )
