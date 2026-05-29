"""ACT-phase loop guards.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)". Two non-
negotiable mechanisms from Reggio:

  1. ``detect_degenerate_loop`` — count consecutive identical tool calls
     and surface a warn/abort signal before the loop runs away.
  2. ``normalize_tool_input`` — handle OpenRouter's quirky
     ``{"_raw": "..."}`` envelope (model emitted malformed JSON; provider
     dumped it raw) plus the bare-JSON-string case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class LoopVerdict(str, Enum):
    OK = "ok"
    WARN = "warn"
    ABORT = "abort"


@dataclass
class ToolCall:
    """Minimal tool-call record for loop detection.

    Loop detection only ever reads :meth:`signature` (name + args). The
    ``is_error`` / ``duration_ms`` fields are populated *after* dispatch
    by the ACT inner loop and consumed only by the soak tool-call ledger
    (v40 build-capability instrumentation); they are ``None`` until a
    call has actually run and stay ``None`` for any batch that aborted
    before dispatch. Not frozen because ``args`` is a dict (already
    unhashable, so frozen never bought real hashability here) and the
    outcome fields are filled in post-construction.
    """

    name: str
    args: dict[str, Any]
    # Populated post-dispatch by ActExecutor; ledger-only.
    is_error: bool | None = None
    duration_ms: float | None = None

    def signature(self) -> tuple[str, str]:
        """Canonical comparable form (outcome fields excluded by design)."""
        return (self.name, json.dumps(self.args, sort_keys=True, default=str))


def detect_degenerate_loop(
    history: list[ToolCall],
    *,
    warn_at: int = 3,
    abort_at: int = 5,
) -> LoopVerdict:
    """Inspect the tail of ``history`` for consecutive identical calls.

    ``warn_at``  consecutive matches → :attr:`LoopVerdict.WARN`
    ``abort_at`` consecutive matches → :attr:`LoopVerdict.ABORT`

    Reggio's defaults (3/5) are a good starting point; tune as data accumulates.
    """
    if not history:
        return LoopVerdict.OK
    if warn_at < 2 or abort_at < warn_at:
        raise ValueError("warn_at must be ≥ 2 and abort_at ≥ warn_at")

    target = history[-1].signature()
    consecutive = 1
    for prev in reversed(history[:-1]):
        if prev.signature() == target:
            consecutive += 1
        else:
            break

    if consecutive >= abort_at:
        return LoopVerdict.ABORT
    if consecutive >= warn_at:
        return LoopVerdict.WARN
    return LoopVerdict.OK


def normalize_tool_input(raw: Any) -> dict[str, Any]:
    """Coerce a tool-call argument blob into a plain dict.

    Handles three shapes:

    - ``None`` or empty → ``{}``
    - ``dict`` — returned as-is, except the OpenRouter ``{"_raw": "<json>"}``
      envelope, which is unwrapped and json-parsed.
    - ``str`` — interpreted as a JSON document; on parse failure, returns ``{}``.

    Anything else returns ``{}``.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        # OpenRouter quirk: a single ``_raw`` key carrying the model's
        # malformed JSON as a string.
        if list(raw.keys()) == ["_raw"] and isinstance(raw["_raw"], str):
            try:
                parsed = json.loads(raw["_raw"])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}



def detect_ping_pong(
    history: list[ToolCall],
    *,
    min_cycle_length: int = 2,
    max_cycle_length: int = 3,
    abort_at_repeats: int = 2,
) -> LoopVerdict:
    """Detect alternating (ping-pong) cycles in the tail of *history*.

    Looks for a repeating pattern of length *min_cycle_length*..*max_cycle_length*
    in the last ``(max_cycle_length * (abort_at_repeats + 1))`` entries.
    Returns ``LoopVerdict.ABORT`` when the same cycle appears *abort_at_repeats*
    times.
    """
    if len(history) < min_cycle_length * 2:
        return LoopVerdict.OK

    sigs = [tc.signature() for tc in history]

    for cycle_len in range(min_cycle_length, max_cycle_length + 1):
        needed = cycle_len * (abort_at_repeats + 1)
        if len(sigs) < needed:
            continue

        tail = sigs[-needed:]
        cycle = tail[:cycle_len]

        matches = True
        for i in range(0, len(tail), cycle_len):
            block = tail[i:i + cycle_len]
            if len(block) < cycle_len:
                break
            if block != cycle:
                matches = False
                break

        if matches:
            return LoopVerdict.ABORT

    return LoopVerdict.OK
