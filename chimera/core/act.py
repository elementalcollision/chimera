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
from .grounding import (
    check_citation_grounding,
    extract_cited_source_files,
    extract_cited_symbols,
    synthesis_guidance_for,
)
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
    "- When you have enough to answer, respond and stop.\n"
    # v4.82 (ADR 0096): explicit writable-scope grant. Across four soaks
    # the agent treated mind/ as the boundary of writable scope and
    # produced spec docs under mind/research/ when INBOX tasks named
    # source files under chimera/. Make the grant explicit so the model
    # does not infer a constraint the runtime never imposed.
    "- Writable roots in this worktree: chimera/, tests/, docs/, "
    "mind/, scripts/, state/. The chimera/ source IS your code — when "
    "an INBOX task names a path under chimera/ or tests/, edit that "
    "file directly via shell or code_exec. Do NOT write a spec under "
    "mind/ in lieu of patching the named file."
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
    # v4.83 (ADR 0095): symbols the synthesis text named but that don't
    # appear in any cited source file. Populated only when
    # finish_reason == "ungrounded_citation".
    ungrounded_citations: list[str] = field(default_factory=list)
    # v4.82 (ADR 0096): code-root paths the INBOX named that the agent
    # never appeared to touch. Populated only when
    # finish_reason == "scope_evasion".
    unedited_paths: list[str] = field(default_factory=list)


_ARTIFACT_PATTERN = re.compile(r"`((?:state|mind|docs)/[A-Za-z0-9_./-]+)`")

# v4.79 (ADR 0093): natural-language "write X to <path>" phrasing. Soak
# tests showed tasks like "Write all of the above to mind/research/x.md"
# slip past validation when the model emitted stop_reason="stop" without
# producing the file. We catch un-backticked paths too, but restrict to
# the same trusted roots as the backtick pattern to limit false
# positives. Verbs are anchored at a word boundary so we don't catch
# "overwrite" or "rewriter".
_NL_ARTIFACT_PATTERN = re.compile(
    r"\b(?:write|writes|save|saves|put|puts|store|stores|create|creates|"
    r"emit|emits|output|outputs|append|appends|persist|persists)\b"
    r"[^.\n`]{0,120}?"
    r"\b(?:to|at|into|in)\s+`?((?:state|mind|docs)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6})`?",
    re.IGNORECASE,
)


# v4.82 (ADR 0096): code-root paths the INBOX explicitly names. These
# are SOURCE files the task is asking the agent to modify — distinct
# from expected_artifacts() (which catches synthesis outputs under
# state/mind/docs). Soak v4 surfaced agents reading the path, then
# writing a spec under mind/research/ instead of touching the file.
# Disjoint from the artifact roots to keep the two checks independent.
#
# v4.85 (ADR 0096 amendment): the union of two passes. The first is the
# legacy "path-shaped string anywhere in the text" regex — it already
# catches most layouts, including the multi-line "Most likely files:
# `X` OR `Y`" wrap that soak v5 surfaced. The second is an explicit
# backtick-only harvest that documents the intent of the disjunctive-
# list shape and gives us a guard against future regex regressions.
_INTENDED_CODE_PATH_PATTERN = re.compile(
    r"`?((?:chimera|tests|scripts)/[A-Za-z0-9_./-]+"
    r"\.(?:py|md|ts|sh|toml|yaml|yml|json))`?"
)
_BACKTICK_CODE_PATH_PATTERN = re.compile(
    r"`((?:chimera|tests|scripts)/[A-Za-z0-9_./-]+"
    r"\.(?:py|md|ts|sh|toml|yaml|yml|json))`"
)


def intended_code_paths(task_text: str) -> list[str]:
    """Return code-root paths the task names. Stable-ordered, deduped.

    Union of the loose path-shape pattern and the strict backtick-only
    pattern. The strict pass exists so the multi-line, parenthetical,
    and OR-list layouts seen in soak v5 fixture 1.b are exercised by
    their own dedicated regex — independent of the loose pass.
    """
    seen: list[str] = []
    for pattern in (_INTENDED_CODE_PATH_PATTERN, _BACKTICK_CODE_PATH_PATTERN):
        for m in pattern.finditer(task_text):
            p = m.group(1)
            if p not in seen:
                seen.append(p)
    return seen


def check_scope_evasion(
    intended: list[str],
    tool_call_history: list[ToolCall],
    write_targets: list[str],
) -> list[str]:
    """Return intended paths that never appear in any tool call arg or
    recorded write target.

    Heuristic: a real edit to ``chimera/x.py`` will surface the path in
    either a shell ``command`` arg (``sed -i ... chimera/x.py``), a
    code_exec snippet, or the post-write ``write_targets`` list. If the
    path appears nowhere, the agent never touched it — that's the
    scope-evasion signal.
    """
    if not intended:
        return []
    blob_parts: list[str] = list(write_targets)
    for call in tool_call_history:
        for v in call.args.values():
            blob_parts.append(str(v))
    blob = " ".join(blob_parts)
    return [p for p in intended if p not in blob]


def check_scope_evasion_strict(
    intended: list[str],
    write_targets: list[str],
) -> list[str]:
    """Stricter variant: a path is "edited" only if it appears in
    ``write_targets`` (populated by the post-tool write-intent extractor).

    v4.85 (ADR 0096 amendment): soak v5 surfaced a task where the agent
    spent 15+ rounds reading the named files (``cat chimera/...``) but
    never edited them. The loose ``check_scope_evasion`` heuristic sees
    the path string in the read command and treats it as a touch. On
    the max_rounds exit path — where the agent failed to converge —
    we want the stricter signal: did anything *actually get written*
    to one of the named files? If not, demote the generic ``max_rounds``
    finish to ``scope_evasion`` so the escalation memory carries the
    diagnosable signal.
    """
    if not intended:
        return []
    targets = set(write_targets)
    return [p for p in intended if p not in targets]


def expected_artifacts(task_text: str) -> list[str]:
    """Extract paths a task promises to write under state/, mind/, or docs/.

    Matches two patterns:
      1. Backtick-quoted paths (canonical form; ADR 0026).
      2. Un-backticked paths after a write-verb + preposition (ADR 0093).

    Used by ACT to verify the model's claimed completion actually
    produced the files the task asked for. Paths are returned relative;
    callers resolve as needed.
    """
    seen: list[str] = []

    def _add(path: str) -> None:
        if path not in seen:
            seen.append(path)

    for m in _ARTIFACT_PATTERN.finditer(task_text):
        _add(m.group(1))
    for m in _NL_ARTIFACT_PATTERN.finditer(task_text):
        _add(m.group(1))
    return seen


def check_artifacts(
    expected: list[str], *, base_dir: Path | None = None
) -> list[str]:
    """Return the subset of ``expected`` paths that are missing or empty.

    v4.79 (ADR 0093): an existing zero-byte file is treated as missing.
    A model that creates the file but never writes content to it is the
    same failure mode as not creating it at all — and is something the
    soak test surfaced when shell tools were partially denied.
    """
    base = base_dir or Path.cwd()
    missing: list[str] = []
    for rel in expected:
        p = base / rel
        try:
            if not p.exists() or not p.is_file() or p.stat().st_size == 0:
                missing.append(rel)
        except OSError:
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
        chronicle: Any = None,
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
        # v4.84 (ADR 0097): optional Chronicle for three-strikes warnings.
        # Loop wires it in; tests and library callers can leave None.
        self._chronicle = chronicle

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

        # v4.84 (ADR 0097): post-escalation remediation. If priors exist
        # for this signature, prepend a hint to the task text. At three
        # strikes, skip the task entirely and write an operator warning
        # to the chronicle.
        from .remediation import (
            SKIPPED_THREE_STRIKES,
            chronicle_warning_body,
            matching_escalations,
            remediation_decision,
        )
        decision = remediation_decision(self._db, task_text=task_text)
        if decision.skip:
            logger.warning(
                "act: skipping task after %d consecutive failures "
                "(three-strikes); writing chronicle warning",
                decision.matched_failures,
            )
            if self._chronicle is not None:
                try:
                    self._chronicle.upsert_section(
                        section_name="Escalation Warnings",
                        body=chronicle_warning_body(
                            task_text,
                            matching_escalations(self._db, task_text=task_text),
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "chronicle.upsert_section raised on three-strikes warning",
                    )
            return ActResult(
                task_text=task_text,
                completed=False,
                rounds=0,
                finish_reason=SKIPPED_THREE_STRIKES,
                failure_reason=(
                    f"three-strikes auto-skip after "
                    f"{decision.matched_failures} prior failures"
                ),
            )

        result = await self._execute_inner(
            task_text,
            cycle=cycle,
            context=context,
            remediation_preamble=decision.preamble,
        )

        # On any non-completion exit, record the failure so the NEXT
        # attempt at a similar signature picks a higher tier.
        #
        # v4.53: ``cost_cap`` is excluded — a cap trip is a *spend*
        # problem, not a *capability* problem. Promoting tier would
        # just burn the cap faster on the next attempt. The cycle
        # rotates and the task gets a fresh budget on the next cycle.
        if not result.completed and result.finish_reason not in (
            "cost_cap", "rolling_hour_cap", "task_budget",
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
        remediation_preamble: str = "",
    ) -> ActResult:
        ctx = context or DispatchContext()
        # v4.84 (ADR 0097): preamble surfacing prior-attempt diagnosis.
        # Prepend on the user message so it stays in the model's
        # immediate context window even after long tool sequences.
        user_message_text = (
            f"{remediation_preamble}{task_text}" if remediation_preamble
            else task_text
        )
        # v4.42: continuation-context detection. If the task text references
        # artifact paths under mind/ or state/ that already exist on disk,
        # the prior cycle made progress; surface the partial state to the
        # model so it doesn't restart from zero.
        continuation_block = _continuation_context(task_text)
        system_prompt = self._build_system_prompt(cycle=cycle)
        if continuation_block:
            system_prompt = f"{system_prompt}\n\n{continuation_block}"
        # v4.83 (ADR 0095): synthesis-task grounding guidance. When the
        # task asks to read source file(s) and produce a verdict, prepend
        # an explicit "quote before you cite" instruction. This is the
        # cheapest of the three grounding controls and tends to dominate
        # the others in practice.
        grounding_guidance = synthesis_guidance_for(task_text)
        if grounding_guidance:
            system_prompt = f"{system_prompt}\n\n{grounding_guidance}"
        messages: list[Message] = [
            Message.system(system_prompt),
            Message.user(user_message_text),
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
            check_task_budget,
            CycleCostCapExceeded,
            RollingHourCostCapExceeded,
            TaskBudgetExceeded,
        )
        from .escalation import _signature as _task_signature
        # v4.60: signature for this task — used by the per-task budget
        # cap AND persisted on every api_calls row so future cycles can
        # sum cross-cycle spend for the same task.
        task_sig = _task_signature(task_text)
        for round_idx in range(effective_max_rounds):
            # v4.53: hard-stop if this cycle has spent over the cap.
            # v4.57: also hard-stop if rolling-60m spend exceeds cap.
            # v4.60: also hard-stop if THIS TASK has exceeded its budget
            # across cycles (catches the stuck-task pattern from the
            # 2026-05-19 burn where escalation re-promoted the same
            # task across 5+ cycles each blowing past the per-cycle cap).
            # All three checked BEFORE the provider call so a tripping
            # cycle exits cleanly without one final expensive request.
            try:
                check_cycle_cost_cap(self._db, cycle)
                check_rolling_hour_cost_cap(self._db)
                check_task_budget(self._db, task_signature=task_sig)
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
            except TaskBudgetExceeded as exc:
                logger.warning(
                    "act: task budget exhausted at $%.2f (budget $%.2f); "
                    "abandoning this task — escalation memory will not "
                    "re-promote",
                    exc.spend_usd, exc.budget_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="task_budget",
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
                    task_signature=task_sig,
                    caller="act",
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
                # v4.60: in-flight task signature for per-task budget.
                task_signature=task_sig,
                # v4.69: caller scope. The CuriosityEngine wraps an
                # ActExecutor — those nested calls still get "act"
                # here; the engine_runs row tracks the count.
                caller="act",
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
                ungrounded: list[str] = []
                if completed:
                    expected = expected_artifacts(task_text)
                    missing = check_artifacts(expected)
                    if missing:
                        completed = False
                        finish_reason = "artifact_missing"
                # v4.83 (ADR 0095): grounding check. Only runs when the
                # artifact check passed — fabricated content in a file
                # that doesn't exist is already caught upstream.
                if completed:
                    cited_files = extract_cited_source_files(task_text)
                    if cited_files:
                        cited_symbols = extract_cited_symbols(
                            response.text or ""
                        )
                        ungrounded = check_citation_grounding(
                            cited_files, cited_symbols,
                        )
                        if ungrounded:
                            completed = False
                            finish_reason = "ungrounded_citation"
                # v4.82 (ADR 0096): scope-evasion check. INBOX task named
                # a path under chimera/|tests/|scripts/ but the agent
                # produced no tool call referencing that path. Soak v4
                # surfaced agents reading the named source file then
                # writing a spec under mind/research/ instead of patching
                # it. Only fires on the clean-stop completion path; the
                # other failure modes already block the false-positive.
                unedited: list[str] = []
                if completed:
                    intended = intended_code_paths(task_text)
                    unedited = check_scope_evasion(
                        intended, history, write_targets,
                    )
                    if unedited:
                        completed = False
                        finish_reason = "scope_evasion"
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
                if unedited and not missing and not ungrounded:
                    failure_reason = (
                        f"scope evasion: named paths {', '.join(unedited)} "
                        f"were not edited"
                    )
                elif ungrounded and not missing:
                    failure_reason = (
                        f"ungrounded citations: {', '.join(ungrounded)} "
                        f"(not found in cited source)"
                    )
                elif missing:
                    failure_reason = f"missing artifacts: {', '.join(missing)}"
                else:
                    failure_reason = None
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
                    ungrounded_citations=ungrounded,
                    unedited_paths=unedited,
                    failure_reason=failure_reason,
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

        # v4.85 (ADR 0096 amendment): scope_evasion on the max_rounds
        # exit path. If the INBOX named source files and write_targets
        # contains none of them, the agent burned its budget without
        # editing the named scope — exactly the soak v5 "Implement the
        # fix per the sketch" failure. Surface the diagnosable signal
        # so escalation memory and the v4.84 remediation hint can use it.
        intended_at_max = intended_code_paths(task_text)
        unedited_at_max = check_scope_evasion_strict(intended_at_max, write_targets)
        finish_reason_at_max = "max_rounds"
        failure_reason_at_max = "exhausted max rounds without final stop"
        if unedited_at_max and not missing_at_max:
            finish_reason_at_max = "scope_evasion"
            failure_reason_at_max = (
                f"scope evasion: named paths {', '.join(unedited_at_max)} "
                f"were not edited"
            )
        return ActResult(
            task_text=task_text,
            completed=False,
            rounds=effective_max_rounds,
            finish_reason=finish_reason_at_max,
            write_targets=write_targets,
            tool_call_history=history,
            final_text=final_text,
            missing_artifacts=missing_at_max,
            unedited_paths=unedited_at_max if finish_reason_at_max == "scope_evasion" else [],
            failure_reason=failure_reason_at_max,
            api_call_count=api_call_count,
        )
