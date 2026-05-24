"""Adaptive per-task budgets for ACT (v4.5 + v4.47 + v4.53).

v4.5 scaled the round budget by task shape — declared artifacts and
named tool keywords. v4.47 adds a tier multiplier so an opus-promoted
task gets more rounds than haiku without changing the task text. This
pairs with the v4.46 task-escalation memory: a task that fails at
haiku auto-promotes to sonnet AND gets a larger budget on the retry.

v4.53 adds a per-cycle USD spend cap that is checked at the *start* of
each ACT round, before the provider call. Trip raises
:class:`CycleCostCapExceeded`; ACT catches it and exits the round loop
with ``finish_reason="cost_cap"``. The cap is intentionally
tier-agnostic — a cycle that burns $2 on opus trips it just like a
cycle that burns $2 on deepseek-flash (implausible but symmetric).
See [ADR 0072](../../docs/adr/0072-cost-runaway-guards.md).

The functions here are pure (with the exception of
:func:`cycle_spend_usd` which reads ``api_calls`` rows from the DB);
ACT calls :func:`dynamic_max_rounds` per task at the start of its loop
and :func:`check_cycle_cost_cap` at the start of each round.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from enum import Enum


# v4.47: per-tier round-budget multipliers. Higher tiers run more
# expensive models so each round costs more — but they also do more
# per round (better planning, broader tool fan-out), so the SAME task
# benefits from a deeper budget when promoted. Numbers tuned so a
# haiku=12 base task lands at sonnet=18, opus=24.
TIER_MULTIPLIERS: dict[str, float] = {
    "haiku": 1.0,
    "sonnet": 1.5,
    "opus": 2.0,
}

# Keywords that strongly suggest a distinct tool-call step. Conservative
# — we only count keywords the task author would naturally use.
_TOOL_KEYWORDS = (
    "web_search",
    "http_fetch",
    "code_exec",
    "shell",
    "spawn_sub_agent",
    "sub-agent",
    "sub agent",
)


def _count_artifacts(task_text: str) -> int:
    from .act import expected_artifacts
    return len(expected_artifacts(task_text))


def _count_tool_keywords(task_text: str) -> int:
    lower = task_text.lower()
    return sum(1 for kw in _TOOL_KEYWORDS if kw in lower)


def dynamic_max_rounds(
    task_text: str,
    *,
    base: int = 12,
    per_artifact: int = 4,
    per_tool: int = 2,
    cap: int = 32,
    tier: str = "haiku",
) -> int:
    """Compute a per-task round budget.

    ``base`` is the floor for any task. ``per_artifact`` adds room for
    each declared output file; ``per_tool`` adds room for each named
    tool keyword. The shape-derived sum is then multiplied by the tier
    factor (v4.47) — opus gets twice the rounds of haiku for the same
    task. ``cap`` is the hard ceiling; v4.47 scales the cap by the same
    multiplier so opus isn't truncated by a haiku-sized ceiling.
    """
    if base < 1:
        base = 1
    if cap < base:
        cap = base
    artifacts = _count_artifacts(task_text)
    tools = _count_tool_keywords(task_text)
    shape_budget = base + per_artifact * artifacts + per_tool * tools

    mult = TIER_MULTIPLIERS.get(tier, 1.0)
    scaled = int(round(shape_budget * mult))
    scaled_cap = int(round(cap * mult))
    return max(int(round(base * mult)), min(scaled_cap, scaled))


# ── v4.53: per-cycle USD spend cap ───────────────────────────────────
#
# After the 2026-05-19 overnight burn (801 opus calls, $229 across one
# stuck task), we hard-cap spend per cycle. ACT calls
# :func:`check_cycle_cost_cap` at the top of each round; if the
# cycle's accumulated spend exceeds the cap, ACT raises
# :class:`CycleCostCapExceeded` and exits the round loop with
# ``finish_reason="cost_cap"``. The cap does NOT promote the tier
# (escalation memory ignores ``cost_cap`` failures) — re-attempting
# the same task on opus just burns the cap again.

_DEFAULT_CYCLE_COST_CAP_USD = 2.00


class CycleCostCapExceeded(Exception):
    """Raised when the cycle's accumulated USD spend exceeds the cap.

    Carries the actual spend and the cap so the caller can log a
    structured event without recomputing.
    """

    def __init__(self, *, spend_usd: float, cap_usd: float, cycle: int):
        self.spend_usd = spend_usd
        self.cap_usd = cap_usd
        self.cycle = cycle
        super().__init__(
            f"cycle {cycle} spend ${spend_usd:.2f} exceeds cap ${cap_usd:.2f}"
        )


def cycle_cost_cap_usd() -> float:
    """Return the per-cycle USD cap, honoring ``CHIMERA_CYCLE_COST_CAP_USD``.

    Default: $2.00. The 2026-05-19 burn averaged ~$10/cycle on the
    stuck task, so $2 is restrictive enough to catch a thrashing
    cycle while still leaving room for a normal opus-rung cycle to
    complete (typical opus cycle pre-burn was $0.05–$0.30).
    """
    raw = os.environ.get("CHIMERA_CYCLE_COST_CAP_USD", "").strip()
    if not raw:
        return _DEFAULT_CYCLE_COST_CAP_USD
    try:
        v = float(raw)
    except ValueError:
        return _DEFAULT_CYCLE_COST_CAP_USD
    # Clamp to a sane range; 0 disables the cap (explicit opt-out).
    if v < 0:
        return 0.0
    return v


# Lazy-loaded model_id → (input_cost_per_mtok, output_cost_per_mtok).
# Built from chimera.providers.tiers on first access so we don't pay
# the import cost when budget.py is loaded by code that never runs
# ACT (e.g., the dynamic_max_rounds tests).
_PRICE_TABLE: dict[str, tuple[float, float]] | None = None


def _price_table() -> dict[str, tuple[float, float]]:
    global _PRICE_TABLE
    if _PRICE_TABLE is not None:
        return _PRICE_TABLE
    from chimera.providers.tiers import MODEL_TIERS, TIER_LADDERS
    table: dict[str, tuple[float, float]] = {}
    for cfg in MODEL_TIERS.values():
        table[cfg.model_id] = (cfg.input_cost_per_mtok, cfg.output_cost_per_mtok)
    for ladder in TIER_LADDERS.values():
        for rung in ladder:
            cfg = rung.config
            table.setdefault(
                cfg.model_id,
                (cfg.input_cost_per_mtok, cfg.output_cost_per_mtok),
            )
    _PRICE_TABLE = table
    return table


def cycle_spend_usd(db: sqlite3.Connection, cycle: int) -> float:
    """Sum the USD spend recorded in ``api_calls`` for the given cycle.

    Cost is computed from ``input_tokens`` and ``output_tokens`` × the
    in-process price table (sourced from
    :data:`chimera.providers.tiers.MODEL_TIERS` and the ladder rungs).
    The ``cost_usd`` column on ``api_calls`` is intentionally ignored
    — it's never populated; see ADR 0072 §"Telemetry gap".
    """
    cur = db.execute(
        "SELECT model_id, "
        "COALESCE(SUM(input_tokens), 0), "
        "COALESCE(SUM(output_tokens), 0) "
        "FROM api_calls "
        "WHERE cycle = ? AND error IS NULL "
        "GROUP BY model_id",
        (cycle,),
    )
    table = _price_table()
    total = 0.0
    for model_id, in_tok, out_tok in cur.fetchall():
        in_price, out_price = table.get(model_id, (0.0, 0.0))
        total += (in_tok / 1_000_000.0) * in_price
        total += (out_tok / 1_000_000.0) * out_price
    return total


def check_cycle_cost_cap(db: sqlite3.Connection, cycle: int) -> None:
    """Raise :class:`CycleCostCapExceeded` if the cycle's spend exceeds the cap.

    No-op when the cap is 0 (disabled via env). ACT calls this at the
    top of each round loop iteration, before the provider call, so a
    cap trip means the *next* call would have pushed us over — the
    current accumulated spend already did.
    """
    cap = cycle_cost_cap_usd()
    if cap <= 0:
        return
    spend = cycle_spend_usd(db, cycle)
    if spend >= cap:
        raise CycleCostCapExceeded(
            spend_usd=spend, cap_usd=cap, cycle=cycle,
        )


# ── v4.57 (ADR 0076): rolling-hour spend cap ────────────────────────
#
# The per-cycle cap (v4.53) catches one runaway cycle, but if the
# escalation memory keeps promoting tasks across multiple cycles and
# each cycle stays just under the cap, total spend can still climb.
# The 2026-05-19 burn averaged $1.70/min for 135 minutes — even with
# the per-cycle cap at $2.00, a sequence of 10 bad cycles back-to-back
# could accumulate $20 before the human noticed. The rolling-hour cap
# is the long-window protection.
#
# Default $20/hour = roughly 10× the per-cycle cap, matching the
# operational "if I see red on the alarm widget for an hour, this run
# is broken" intuition.

_DEFAULT_ROLLING_HOUR_CAP_USD = 20.00


class RollingHourCostCapExceeded(Exception):
    """Raised when accumulated spend in the rolling 60-minute window
    exceeds the rolling-hour cap.

    Distinct exception type from :class:`CycleCostCapExceeded` so ACT
    can log + report each cause separately (and operators can tell at
    a glance whether one cycle ran away or whether the day's been a
    slow burn).
    """

    def __init__(self, *, spend_usd: float, cap_usd: float, window_minutes: int = 60):
        self.spend_usd = spend_usd
        self.cap_usd = cap_usd
        self.window_minutes = window_minutes
        super().__init__(
            f"rolling-{window_minutes}m spend ${spend_usd:.2f} "
            f"exceeds cap ${cap_usd:.2f}"
        )


def rolling_hour_cap_usd() -> float:
    """Return the rolling-hour USD cap, honoring CHIMERA_ROLLING_HOUR_CAP_USD.

    Default: $20.00. The 2026-05-19 burn averaged $1.70/min × 60min
    = $102/hour — five times this cap. Set to 0 to disable.
    """
    raw = os.environ.get("CHIMERA_ROLLING_HOUR_CAP_USD", "").strip()
    if not raw:
        return _DEFAULT_ROLLING_HOUR_CAP_USD
    try:
        v = float(raw)
    except ValueError:
        return _DEFAULT_ROLLING_HOUR_CAP_USD
    if v < 0:
        return 0.0
    return v


def rolling_spend_usd(db: sqlite3.Connection, *, minutes: int = 60) -> float:
    """Sum USD spend over the last ``minutes``.

    Uses the same price table as :func:`cycle_spend_usd` but
    time-bounded by ``created_at >= datetime('now', '-N minutes')``.
    Per-call cost_usd column is ignored even when populated (v4.57+)
    — we recompute from tokens × current price table so a tier-price
    update applies retroactively when read.
    """
    m = max(1, min(1440, int(minutes)))
    # NOTE: production writes ISO timestamps with T-separator and
    # +00:00 tz (``_utc_now_iso``); SQLite's ``datetime('now', '-N min')``
    # produces space-separated, no-tz. Raw string comparison would
    # silently overcount. Wrap both sides in ``datetime()`` to
    # normalize.
    cur = db.execute(
        "SELECT model_id, "
        "  COALESCE(SUM(input_tokens), 0), "
        "  COALESCE(SUM(output_tokens), 0) "
        "FROM api_calls "
        "WHERE error IS NULL "
        f"  AND datetime(created_at) >= datetime('now', '-{m} minutes') "
        "GROUP BY model_id"
    )
    table = _price_table()
    total = 0.0
    for model_id, in_tok, out_tok in cur.fetchall():
        in_price, out_price = table.get(model_id, (0.0, 0.0))
        total += (in_tok / 1_000_000.0) * in_price
        total += (out_tok / 1_000_000.0) * out_price
    return total


def check_rolling_hour_cost_cap(db: sqlite3.Connection) -> None:
    """Raise :class:`RollingHourCostCapExceeded` if 60-min spend > cap.

    Companion to :func:`check_cycle_cost_cap`. ACT calls both at the
    top of each round; tripping either exits the round loop. No-op
    when the cap is 0 (disabled via env).
    """
    cap = rolling_hour_cap_usd()
    if cap <= 0:
        return
    spend = rolling_spend_usd(db, minutes=60)
    if spend >= cap:
        raise RollingHourCostCapExceeded(
            spend_usd=spend, cap_usd=cap, window_minutes=60,
        )


# ── v4.60 (ADR 0079): per-task budget cap ──────────────────────────
#
# The cycle cap stops one runaway cycle. The rolling-hour cap stops a
# slow burn across cycles. Neither stops a single STUCK TASK that
# keeps getting promoted by escalation memory and burning a fresh
# per-cycle cap on every retry. The 2026-05-19 burn was exactly this
# pattern: one task (dashboard honesty audit) re-attempted across 5+
# cycles, each cycle blowing well past the eventual $2 cap. A
# per-task budget makes "this task is too expensive — abandon it"
# an explicit, machine-enforced condition.
#
# Default $5/task = ~2.5× the per-cycle cap; legitimate multi-cycle
# tasks (e.g. tier-promoted research from haiku → sonnet) fit; tasks
# that keep failing don't.

_DEFAULT_TASK_BUDGET_USD = 5.00


class TaskBudgetExceeded(Exception):
    """Raised when a task has accumulated more than the per-task budget."""

    def __init__(self, *, spend_usd: float, budget_usd: float, signature: str):
        self.spend_usd = spend_usd
        self.budget_usd = budget_usd
        self.signature = signature
        sig_preview = signature[:60] + ("…" if len(signature) > 60 else "")
        super().__init__(
            f"task signature spend ${spend_usd:.2f} "
            f"exceeds budget ${budget_usd:.2f} (sig: {sig_preview})"
        )


def task_budget_usd() -> float:
    """Per-task USD budget, honoring CHIMERA_TASK_BUDGET_USD.

    Default: $5.00. Set to 0 to disable.
    """
    raw = os.environ.get("CHIMERA_TASK_BUDGET_USD", "").strip()
    if not raw:
        return _DEFAULT_TASK_BUDGET_USD
    try:
        v = float(raw)
    except ValueError:
        return _DEFAULT_TASK_BUDGET_USD
    if v < 0:
        return 0.0
    return v


def task_spend_usd(db: sqlite3.Connection, *, task_signature: str) -> float:
    """Sum spend across all cycles that ran this task signature.

    Errored rows excluded. Token-driven recompute (same as cycle and
    rolling helpers) so a tier-price update applies retroactively
    when read.
    """
    if not task_signature:
        return 0.0
    try:
        cur = db.execute(
            "SELECT model_id, "
            "  COALESCE(SUM(input_tokens), 0), "
            "  COALESCE(SUM(output_tokens), 0) "
            "FROM api_calls "
            "WHERE error IS NULL AND task_signature = ? "
            "GROUP BY model_id",
            (task_signature,),
        )
    except sqlite3.OperationalError:
        # task_signature column missing — caller is on a pre-v4.60 DB.
        return 0.0
    table = _price_table()
    total = 0.0
    for model_id, in_tok, out_tok in cur.fetchall():
        in_price, out_price = table.get(model_id, (0.0, 0.0))
        total += (in_tok / 1_000_000.0) * in_price
        total += (out_tok / 1_000_000.0) * out_price
    return total


def check_task_budget(db: sqlite3.Connection, *, task_signature: str) -> None:
    """Raise :class:`TaskBudgetExceeded` if this task has spent over its budget.

    No-op when the budget is 0 (disabled) or the signature is empty.
    Called by ACT at the top of each round alongside the cycle and
    rolling-hour caps.
    """
    if not task_signature:
        return
    budget = task_budget_usd()
    if budget <= 0:
        return
    spend = task_spend_usd(db, task_signature=task_signature)
    if spend >= budget:
        raise TaskBudgetExceeded(
            spend_usd=spend, budget_usd=budget, signature=task_signature,
        )


# ── Honcho-inspired enhancements (ADR 0123) ─────────────────────────
#
# Two trivial additions ported from Honcho's design (NOT integrated as
# a dependency; see ADR 0123 for the inspire-don't-integrate rationale):
#
#   1. ReasoningTier — explicit cost/quality knob on calls that route
#      to dialectic/witness/reflection. Defaults to NORMAL so existing
#      call sites keep behavior; future PRs wire tiers to model
#      selection. Mirrors Honcho's five-level dialectic reasoning knob.
#
#   2. Context.to_openai() — token-aware prompt-assembly builder. Pure
#      utility; truncates middle messages first under budget. Mirrors
#      Honcho's session.context(...).to_openai() pattern.
#
# Both are backward-compatible additions — nothing existing changes.


class ReasoningTier(Enum):
    """Cost/quality knob for LLM-routed calls (dialectic/witness/reflection).

    The tier is plumbed *through* existing budget and model-selection
    logic. Call sites that don't pass a tier get :attr:`NORMAL`, which
    keeps the legacy tier string the call site already uses.
    """

    MINIMAL = "minimal"   # cheap, fast, structured-output only
    NORMAL = "normal"     # current default behavior
    DEEP = "deep"         # opus-class, agentic, multi-round
    MAX = "max"           # cross-provider witness panel (existing v4.110+)


# ADR 0127: mapping from the high-level ReasoningTier cost/quality
# knob to the existing tier-string ladder consumed by
# :func:`chimera.providers.tiers.select_rung`. Kept narrow on purpose
# — MAX intentionally falls back to ``opus`` because the witness-panel
# behavior (ADR 0107) is selected at a different layer (panel
# assembly), not at single-call routing.
_REASONING_TIER_TO_LADDER: dict[ReasoningTier, str] = {
    ReasoningTier.MINIMAL: "haiku",
    ReasoningTier.NORMAL:  "sonnet",
    ReasoningTier.DEEP:    "opus",
    ReasoningTier.MAX:     "opus",
}


def tier_for_reasoning(
    reasoning_tier: ReasoningTier | None,
    *,
    default: str = "sonnet",
) -> str:
    """Resolve a :class:`ReasoningTier` to the legacy tier string.

    Returns ``default`` when ``reasoning_tier`` is ``None`` so existing
    call sites that haven't opted into the enum keep their literal
    tier string. Pass a real :class:`ReasoningTier` to override.
    """
    if reasoning_tier is None:
        return default
    return _REASONING_TIER_TO_LADDER.get(reasoning_tier, default)


def _estimate_tokens(text: str) -> int:
    """Approximate token count for ``text``.

    Uses ``tiktoken`` (cl100k_base) when installed; otherwise falls
    back to a ~4-chars-per-token heuristic. No new dependency is
    introduced — tiktoken is optional.
    """
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError:
        return max(1, (len(text) + 3) // 4)
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, (len(text) + 3) // 4)


def _message_tokens(message: dict) -> int:
    """Token count for one openai-style chat message dict."""
    content = message.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return _estimate_tokens(str(content)) + 4  # +4 for role + framing


@dataclass
class Context:
    """Token-aware prompt-assembly bundle.

    Mirrors Honcho's ``session.context(...).to_openai()`` shape: hold
    a system prompt + a message list, then materialise an
    openai.chat.completions.create-compatible payload that fits within
    ``max_tokens``. Middle messages are truncated first so the system
    prompt and the most recent two user/assistant turns are preserved.
    """

    system: str | None = None
    messages: list[dict] = field(default_factory=list)
    max_tokens: int = 8_000

    def estimated_tokens(self) -> int:
        total = _estimate_tokens(self.system or "")
        for m in self.messages:
            total += _message_tokens(m)
        return total

    def to_openai(self, *, model: str | None = None) -> dict:
        """Return a payload shaped for ``client.chat.completions.create``.

        Preserves the system prompt + last two messages and drops
        middle messages from oldest-after-the-head until the estimate
        fits ``max_tokens``. The payload is the dict the openai SDK
        accepts as ``**kwargs``; ``model`` is included when provided.
        """
        kept: list[dict] = list(self.messages)
        # Reserve the last 2 messages (most recent turn) plus the
        # first message (often anchoring context) when trimming.
        while kept and self.estimated_tokens_for(kept) > self.max_tokens:
            if len(kept) <= 3:
                break
            # Drop the second message (index 1) — preserves head + tail.
            kept.pop(1)

        payload: dict = {"messages": []}
        if self.system:
            payload["messages"].append({"role": "system", "content": self.system})
        payload["messages"].extend(kept)
        if model is not None:
            payload["model"] = model
        return payload

    def estimated_tokens_for(self, messages: list[dict]) -> int:
        total = _estimate_tokens(self.system or "")
        for m in messages:
            total += _message_tokens(m)
        return total

