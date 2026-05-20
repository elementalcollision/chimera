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

import asyncio
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
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
from ..providers.tiers import eligible_rungs, select_rung
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


_CONTINUATION_HEAD = 800
_CONTINUATION_TAIL = 800
_CONTINUATION_INLINE_MAX = 2000  # files smaller than this embed in full
_CONTINUATION_MAX_PATHS = 6


def _continuation_context(task_text: str) -> str:
    """v4.42 / v4.43: build a "Continuation context" block for the system
    prompt summarising any artifact paths the task references that already
    exist on disk. Tells the model "the prior cycle did X — continue from
    there, do not restart from zero."

    v4.43 improvement: small files (<2KB) embed in full; larger files
    show HEAD + TAIL so the model sees both the structural top and the
    most recent progress (the tail is where partial work usually
    accumulates — appended sections, last-written paragraphs).

    Returns "" when no continuation is detected (fresh task).
    """
    expected = expected_artifacts(task_text)
    if not expected:
        return ""
    base = Path.cwd()
    blocks: list[str] = []
    for rel in expected[:_CONTINUATION_MAX_PATHS]:
        p = base / rel
        if not p.exists() or not p.is_file():
            continue
        try:
            st = p.stat()
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_lines = text.count("\n")
        if len(text) <= _CONTINUATION_INLINE_MAX:
            preview = text
            marker = ""
        else:
            head = text[:_CONTINUATION_HEAD].rstrip()
            tail = text[-_CONTINUATION_TAIL:].lstrip()
            elided = len(text) - _CONTINUATION_HEAD - _CONTINUATION_TAIL
            preview = (
                f"{head}\n"
                f"  ...[{elided} bytes elided from middle]...\n"
                f"{tail}"
            )
            marker = ""
        blocks.append(
            f"- `{rel}` ({st.st_size} bytes, {n_lines} lines):\n"
            f"  ```\n  {preview}{marker}\n  ```"
        )
    if not blocks:
        return ""
    body = "\n".join(blocks)
    return (
        "## Continuation context\n"
        "Prior cycle(s) produced these artifacts already. CONTINUE the work "
        "(append, finish, fix the specific gaps) — do NOT re-research, "
        "re-fetch, or re-validate content that's clearly already present. "
        "Treat existing content as authoritative unless it is obviously "
        "truncated or syntactically broken. Your goal is to land the "
        "missing pieces and STOP:\n"
        f"{body}"
    )


def _schema_hint(registry, tool_name: str, args: dict[str, Any]) -> str:
    """v4.41: render a one-line schema hint for the model on validation
    failure. Format: ``hint: <name>({required: ..., received: ...})``."""
    try:
        entry = registry.get(tool_name)
    except Exception:  # noqa: BLE001
        return ""
    if entry is None:
        return f"hint: unknown tool {tool_name!r}; check the registered tool list."
    schema = entry.schema or {}
    fn = schema.get("function") if schema.get("type") == "function" else schema
    params = (fn or {}).get("parameters") or {}
    props = params.get("properties") or {}
    required = list(params.get("required") or [])
    received = sorted(args.keys()) if isinstance(args, dict) else []
    fields: list[str] = []
    for key in required:
        prop = props.get(key) or {}
        fields.append(f"{key}: {prop.get('type', 'any')} (required)")
    optional = [k for k in props.keys() if k not in required]
    for key in optional[:4]:
        prop = props[key]
        fields.append(f"{key}: {prop.get('type', 'any')}")
    schema_line = ", ".join(fields) or "(no parameters)"
    return (
        f"hint: {tool_name}({{ {schema_line} }}). "
        f"received keys: {received or '[]'}."
    )


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
    missing_artifacts: list[str] = field(default_factory=list)


_ARTIFACT_PATTERN = re.compile(r"`((?:state|mind)/[A-Za-z0-9_./-]+)`")


def expected_artifacts(task_text: str) -> list[str]:
    """Extract backtick-quoted paths under state/ or mind/ from a task line.

    Used by ACT to verify the model's claimed completion actually produced
    the files the task asked for (L-1, ADR 0026). The path is treated as
    relative to the working directory; callers resolve as needed.
    """
    seen: list[str] = []
    for m in _ARTIFACT_PATTERN.finditer(task_text):
        path = m.group(1)
        if path not in seen:
            seen.append(path)
    return seen


def check_artifacts(
    expected: list[str], *, base_dir: Path | None = None
) -> list[str]:
    """Return the subset of ``expected`` paths that do NOT exist on disk."""
    base = base_dir or Path.cwd()
    missing: list[str] = []
    for rel in expected:
        if not (base / rel).exists():
            missing.append(rel)
    return missing


class ActExecutor:
    """Runs the tool-using inner loop for a single task."""

    # v4.71: tier-aware output-token budget. The flat 2048 cap was
    # producing repeated ``finish=length`` truncations on opus tool_use
    # turns (recorded in cycle 27 history meta). Anthropic's published
    # output ceilings: haiku-4.5 ≈ 8k, sonnet-4.6 ≈ 64k extended
    # thinking / 8k standard, opus-4.7 ≈ 32k. We pick conservative
    # defaults below the ceilings and let operators override via
    # ``CHIMERA_ACT_MAX_TOKENS`` (global) or
    # ``CHIMERA_ACT_MAX_TOKENS_<TIER>`` (per-tier). See
    # docs/runbook.md §"Output-token budget".
    _TIER_MAX_TOKENS: dict[str, int] = {
        "haiku": 4096,
        "sonnet": 8192,
        "opus": 16384,
    }

    @classmethod
    def _resolve_max_tokens(cls, tier: str) -> int:
        import os
        per_tier = os.environ.get(f"CHIMERA_ACT_MAX_TOKENS_{tier.upper()}")
        if per_tier and per_tier.isdigit():
            return int(per_tier)
        glob = os.environ.get("CHIMERA_ACT_MAX_TOKENS")
        if glob and glob.isdigit():
            return int(glob)
        return cls._TIER_MAX_TOKENS.get(tier, 4096)

    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        tier: str = "haiku",
        max_rounds: int = 12,
        max_tokens: int | None = None,
        system_prompt_extra: str = DEFAULT_SYSTEM_PROMPT_EXTRA,
    ) -> None:
        self._dispatcher = dispatcher
        self._providers = providers
        self._db = db
        self._tier = tier
        self._max_rounds = max_rounds
        # v4.71: None → tier-aware default. Explicit ints still honoured
        # (preserves backward compatibility with existing callers/tests).
        self._max_tokens = (
            max_tokens if max_tokens is not None else self._resolve_max_tokens(tier)
        )
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
        # v4.46: persistent task-escalation memory. If this task's
        # signature has failed before, start at a higher tier than the
        # default — avoids re-running deepseek-flash 26 times on a job
        # that demonstrably needs sonnet.
        from .escalation import recommended_tier, record_failure
        promoted_tier = recommended_tier(
            self._db, task_text=task_text, default_tier=self._tier,
        )
        if promoted_tier != self._tier:
            logger.info(
                "act: escalating tier %s → %s based on prior failures",
                self._tier, promoted_tier,
            )
            self._tier = promoted_tier

        result = await self._execute_inner(task_text, cycle=cycle, context=context)

        # On any non-completion exit, record the failure so the NEXT
        # attempt at a similar signature picks a higher tier.
        #
        # v4.53: ``cost_cap`` is excluded — a cap trip is a *spend*
        # problem, not a *capability* problem. Promoting tier would
        # just burn the cap faster on the next attempt. The cycle
        # rotates and the task gets a fresh budget on the next cycle.
        if not result.completed and result.finish_reason not in (
            "cost_cap", "rolling_hour_cap",
        ):
            try:
                record_failure(
                    self._db,
                    task_text=task_text,
                    tier=self._tier,
                    finish_reason=result.finish_reason,
                    rounds_used=result.rounds,
                    cycle=cycle,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "task_escalations record_failure raised; continuing",
                )
        return result

    async def _execute_inner(
        self,
        task_text: str,
        *,
        cycle: int,
        context: DispatchContext | None = None,
    ) -> ActResult:
        ctx = context or DispatchContext()
        # v4.42: continuation-context detection. If the task text references
        # artifact paths under mind/ or state/ that already exist on disk,
        # the prior cycle made progress; surface the partial state to the
        # model so it doesn't restart from zero.
        continuation_block = _continuation_context(task_text)
        system_prompt = self._build_system_prompt(cycle=cycle)
        if continuation_block:
            system_prompt = f"{system_prompt}\n\n{continuation_block}"
        messages: list[Message] = [
            Message.system(system_prompt),
            Message.user(task_text),
        ]
        tools_schema = self._dispatcher.registry.schemas()
        history: list[ToolCall] = []
        write_targets: list[str] = []
        api_call_count = 0
        final_text = ""
        stop_reason = ""

        # v3.11: walk all eligible rungs cheapest-first. We start on the
        # cheapest; on a provider error we record retry_exhausted and
        # escalate to the next rung. Out of rungs → give up.
        rung_list = [
            r for r in eligible_rungs(self._tier, requires_tools=True)
            if self._provider_for(r) is not None
        ]
        if not rung_list:
            return ActResult(
                task_text=task_text,
                completed=False,
                rounds=0,
                finish_reason="provider_unavailable",
                failure_reason=f"no provider available for tier {self._tier!r}",
            )
        rung_idx = 0
        rung = rung_list[0]
        provider = self._provider_for(rung)
        assert provider is not None
        last_provider_error: str | None = None

        # v4.5: per-task adaptive budget — scales with declared artifacts
        # and named tool keywords, capped at 32. v4.47: also scaled by
        # the (possibly v4.46-promoted) tier so opus gets more rounds
        # than haiku for the same task.
        from .budget import dynamic_max_rounds

        effective_max_rounds = dynamic_max_rounds(
            task_text, base=self._max_rounds, tier=self._tier,
        )
        # v4.50: wall-clock anchor used to measure round-boundary latency
        # — the time between the prior round's last tool completion and
        # this round's provider call. None on the very first round.
        import time as _time
        prior_tools_done_at: float | None = None
        from .budget import (
            check_cycle_cost_cap,
            check_rolling_hour_cost_cap,
            CycleCostCapExceeded,
            RollingHourCostCapExceeded,
        )
        for round_idx in range(effective_max_rounds):
            # v4.53: hard-stop if this cycle has spent over the cap.
            # v4.57: also hard-stop if rolling-60m spend exceeds cap.
            # Both checked BEFORE the provider call so a tripping cycle
            # exits cleanly without one final expensive request.
            try:
                check_cycle_cost_cap(self._db, cycle)
                check_rolling_hour_cost_cap(self._db)
            except CycleCostCapExceeded as exc:
                logger.warning(
                    "act: cycle %d cost cap tripped at $%.2f (cap $%.2f); "
                    "exiting round loop without tier promotion",
                    exc.cycle, exc.spend_usd, exc.cap_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="cost_cap",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )
            except RollingHourCostCapExceeded as exc:
                logger.warning(
                    "act: rolling-60m cost cap tripped at $%.2f (cap $%.2f); "
                    "exiting round loop without tier promotion",
                    exc.spend_usd, exc.cap_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="rolling_hour_cap",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )
            round_boundary_ms: int | None = None
            if prior_tools_done_at is not None:
                round_boundary_ms = int(
                    (_time.perf_counter() - prior_tools_done_at) * 1000.0
                )
            try:
                response = await provider.complete_with_tools(
                    messages=messages,
                    model_id=self._model_id_for(rung),
                    tools=tools_schema,
                    max_tokens=self._max_tokens,
                )
            except Exception as exc:
                last_provider_error = str(exc)
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
                    outcome="retry_exhausted",
                )
                rung_idx += 1
                if rung_idx >= len(rung_list):
                    return ActResult(
                        task_text=task_text,
                        completed=False,
                        rounds=round_idx,
                        finish_reason="provider_error",
                        failure_reason=last_provider_error,
                        api_call_count=api_call_count,
                    )
                rung = rung_list[rung_idx]
                provider = self._provider_for(rung)
                assert provider is not None
                continue

            api_call_count += 1
            # v4.57 (ADR 0076): compute and persist cost_usd at write
            # time. The dashboard widget computed cost client-side from
            # tokens × tier prices; that still works, but the DB column
            # being empty meant cycle-cost queries (and chimera doctor)
            # couldn't see real spend. Now both paths agree.
            from .budget import _price_table as _bp_price_table
            _prices = _bp_price_table()
            _in_price, _out_price = _prices.get(response.model_id, (0.0, 0.0))
            _in_tok = response.input_tokens or 0
            _out_tok = response.output_tokens or 0
            cost_usd = (
                (_in_tok / 1_000_000.0) * _in_price
                + (_out_tok / 1_000_000.0) * _out_price
            )
            record_api_call(
                self._db,
                cycle=cycle,
                provider=provider.name,
                model_id=response.model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=cost_usd if cost_usd > 0 else None,
                latency_ms=response.latency_ms,
                finish_reason=response.stop_reason,
                # v4.33: parallel-tool fan-out telemetry.
                tool_uses_count=len(response.tool_uses or []),
                # v4.50: time between prior tool completion and this call.
                round_boundary_latency_ms=round_boundary_ms,
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

            # No tools → done. v4.3: verify any path-shaped artifacts the
            # task asked for actually exist before flipping completed=True.
            if not response.tool_uses or response.stop_reason in ("stop", "length"):
                completed = response.stop_reason == "stop"
                finish_reason = response.stop_reason
                missing: list[str] = []
                if completed:
                    expected = expected_artifacts(task_text)
                    missing = check_artifacts(expected)
                    if missing:
                        completed = False
                        finish_reason = "artifact_missing"
                # v4.5 + v4.10: fragmentation is the same shape whether
                # ACT ran out of rounds OR the model said `stop` without
                # producing the artifact. Hook fires on either path.
                if missing:
                    try:
                        from .adaptation import (
                            maybe_propose_synthesis_skill,
                            record_fragmentation,
                        )
                        record_fragmentation(
                            cycle=cycle,
                            task_text=task_text,
                            rounds_used=round_idx + 1,
                            tool_call_count=len(history),
                            missing_artifacts=missing,
                        )
                        maybe_propose_synthesis_skill(
                            self._db, cycle=cycle, task_text=task_text,
                            missing_artifacts=missing,
                        )
                    except Exception:
                        logger.exception(
                            "fragmentation log / auto-proposal failed; continuing"
                        )
                return ActResult(
                    task_text=task_text,
                    completed=completed,
                    rounds=round_idx + 1,
                    finish_reason=finish_reason,
                    write_targets=write_targets,
                    tool_call_history=history,
                    final_text=final_text,
                    api_call_count=api_call_count,
                    missing_artifacts=missing,
                    failure_reason=(
                        f"missing artifacts: {', '.join(missing)}" if missing else None
                    ),
                )

            # Append assistant turn with the model's tool_use blocks.
            messages.append(Message.assistant(response.text, response.tool_uses))

            # v4.18: dispatch the batch of tool_uses concurrently. The
            # Anthropic API emits multiple tool_use blocks in a single
            # response when the model wants parallel calls; running them
            # serially throws that latency back away. We still append each
            # call to history first (so detect_degenerate_loop sees the
            # full batch before any dispatch fires).
            batch_args: list[dict[str, Any]] = []
            for tu in response.tool_uses:
                args = normalize_tool_input(tu.input)
                batch_args.append(args)
                history.append(ToolCall(name=tu.name, args=args))

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

            async def _run_one(tu_id: str, name: str, args: dict[str, Any]) -> ToolResultBlock:
                try:
                    output = await self._dispatcher.dispatch(name, args, ctx)
                    return ToolResultBlock(tool_use_id=tu_id, content=output, is_error=False)
                except ToolDenied as exc:
                    return ToolResultBlock(
                        tool_use_id=tu_id, content=f"tool denied: {exc}", is_error=True
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    # v4.41: input-validation failure. Teach the model the
                    # correct shape so it can self-correct in the next
                    # round, instead of seeing only the raw exception.
                    hint = _schema_hint(self._dispatcher.registry, name, args)
                    return ToolResultBlock(
                        tool_use_id=tu_id,
                        content=f"error: {exc}\n{hint}".rstrip(),
                        is_error=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("tool dispatch failed: %s", name)
                    return ToolResultBlock(
                        tool_use_id=tu_id, content=f"error: {exc}", is_error=True
                    )

            if len(response.tool_uses) > 1:
                logger.info(
                    "act: dispatching %d tool_uses in parallel: %s",
                    len(response.tool_uses),
                    [tu.name for tu in response.tool_uses],
                )

            tool_results: list[ToolResultBlock] = list(
                await asyncio.gather(
                    *[
                        _run_one(tu.id, tu.name, args)
                        for tu, args in zip(response.tool_uses, batch_args)
                    ]
                )
            )
            # v4.50: capture wall-clock at the last tool's completion so
            # the NEXT round can record the round-boundary latency.
            prior_tools_done_at = _time.perf_counter()

            # Track write_targets the agent may have produced. The shell tool
            # doesn't write, but future write tools will populate this via the
            # path-extraction heuristic on tool args.
            for call in history[-len(response.tool_uses) :]:
                for path in extract_target_paths(" ".join(map(str, call.args.values()))):
                    if path not in write_targets:
                        write_targets.append(path)

            messages.append(Message.tool_results(tool_results))

        # v4.5: max_rounds + declared artifacts missing = fragmentation.
        # Log it; if the signature recurred enough, auto-propose a
        # focused synthesis skill via the mutation queue.
        missing_at_max = check_artifacts(expected_artifacts(task_text))
        if missing_at_max:
            try:
                from .adaptation import (
                    maybe_propose_synthesis_skill,
                    record_fragmentation,
                )

                record_fragmentation(
                    cycle=cycle,
                    task_text=task_text,
                    rounds_used=effective_max_rounds,
                    tool_call_count=len(history),
                    missing_artifacts=missing_at_max,
                )
                maybe_propose_synthesis_skill(
                    self._db,
                    cycle=cycle,
                    task_text=task_text,
                    missing_artifacts=missing_at_max,
                )
            except Exception:
                logger.exception(
                    "fragmentation log / auto-proposal failed; continuing"
                )

        return ActResult(
            task_text=task_text,
            completed=False,
            rounds=effective_max_rounds,
            finish_reason="max_rounds",
            write_targets=write_targets,
            tool_call_history=history,
            final_text=final_text,
            missing_artifacts=missing_at_max,
            failure_reason="exhausted max rounds without final stop",
            api_call_count=api_call_count,
        )
