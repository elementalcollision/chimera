"""Tool dispatch + multi-layer policy pipeline.

Per ADR 0001 §"Tool dispatch policy": OpenClaw-style pipeline applied
PRE-dispatch. Layers, in order:

  1. Global deny list  (never invoke regardless of context)
  2. Per-context deny list
  3. Per-context allow list (if non-empty, must include the tool)
  4. Availability check (Hermes-style TTL-cached check_fn)
  5. requires_env enforcement (named env vars must be set)

The dispatcher never invokes a denied tool. Result is truncated to
``max_result_size_chars`` before return.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .registry import ToolRegistry, default_registry


class ToolError(Exception):
    """Base error for tool dispatch."""


class ToolDenied(ToolError):
    """Policy rejected the call."""


class ToolUnavailable(ToolError):
    """Tool exists but check_fn / requires_env failed."""


class ToolNotFound(ToolError):
    """No entry registered under that name."""


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    layer: str  # which pipeline layer made the call

    @property
    def allowed(self) -> bool:
        return self.decision is PolicyDecision.ALLOW


@dataclass
class DispatchContext:
    """Per-call context — trust tier, session, allow/deny overrides."""

    trust_tier: str = "T0"
    session_id: str = "default"
    allow: frozenset[str] = field(default_factory=frozenset)
    deny: frozenset[str] = field(default_factory=frozenset)
    # Reggio's elevation flag (PR #58 territory): bypasses the shell allow-list.
    elevated: bool = False


# Global deny — tools that are NEVER invokable regardless of context.
# Populated by individual tool modules at import time; can also be tuned
# via CHIMERA_GLOBAL_TOOL_DENY env (comma-separated).
_GLOBAL_DENY: set[str] = set()


def add_global_deny(*names: str) -> None:
    _GLOBAL_DENY.update(names)


def clear_global_deny() -> None:
    _GLOBAL_DENY.clear()


def _env_global_deny() -> set[str]:
    raw = os.environ.get("CHIMERA_GLOBAL_TOOL_DENY", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


class Dispatcher:
    """Routes tool calls through the policy pipeline."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or default_registry()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    # ── policy ─────────────────────────────────────────────

    def check_policy(self, tool_name: str, context: DispatchContext) -> PolicyResult:
        # Layer 0: tool exists
        entry = self._registry.get(tool_name)
        if entry is None:
            return PolicyResult(PolicyDecision.DENY, f"unknown tool: {tool_name!r}", "registry")

        # Layer 1: global deny (in-process + env)
        if tool_name in _GLOBAL_DENY or tool_name in _env_global_deny():
            return PolicyResult(PolicyDecision.DENY, "globally denied", "global_deny")

        # Layer 2: per-context deny
        if tool_name in context.deny:
            return PolicyResult(PolicyDecision.DENY, "denied by context", "context_deny")

        # Layer 3: per-context allow (allow-list mode)
        if context.allow and tool_name not in context.allow:
            return PolicyResult(
                PolicyDecision.DENY, "not in context allow-list", "context_allow"
            )

        # Layer 4: requires_env
        for var in entry.requires_env:
            if not os.environ.get(var):
                return PolicyResult(
                    PolicyDecision.DENY, f"missing env: {var}", "requires_env"
                )

        # Layer 5: availability (TTL-cached check_fn)
        if not self._registry.is_available(tool_name):
            return PolicyResult(PolicyDecision.DENY, "check_fn failed", "availability")

        return PolicyResult(PolicyDecision.ALLOW, "ok", "ok")

    # ── dispatch ───────────────────────────────────────────

    async def dispatch(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: DispatchContext | None = None,
    ) -> str:
        ctx = context or DispatchContext()
        result = self.check_policy(tool_name, ctx)
        if not result.allowed:
            raise ToolDenied(f"[{result.layer}] {result.reason}")
        entry = self._registry.get(tool_name)
        assert entry is not None  # check_policy guarantees this
        output = await entry.handler(args, ctx)
        if not isinstance(output, str):
            output = str(output)
        if len(output) > entry.max_result_size_chars:
            output = output[: entry.max_result_size_chars] + "\n[truncated]"
        return output
