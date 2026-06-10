"""Tool registry — Hermes-style declarative registration.

Per ADR 0001 §"Tool registry": `register(name, toolset, schema, handler,
check_fn, ...)` with TTL-cached availability checks. Re-implemented from
the Hermes pattern; no Hermes runtime dependency.

OpenAI-compatible JSON schemas. One global registry per process is the
common case; tests construct local registries.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Handler signature: (args: dict, context: DispatchContext) -> str.
# `context` is imported lazily in dispatch.py to avoid a cycle.
ToolHandler = Callable[[dict[str, Any], Any], Awaitable[str]]
CheckFn = Callable[[], bool]


@dataclass(frozen=True)
class ToolEntry:
    """One registered tool."""

    name: str
    toolset: str
    schema: dict[str, Any]               # OpenAI-shaped {"type": "function", "function": {...}}
    handler: ToolHandler
    check_fn: CheckFn | None = None      # availability probe
    requires_env: tuple[str, ...] = ()
    max_result_size_chars: int = 32_000
    description: str = ""


class ToolRegistry:
    """Holds the live set of tools, TTL-caches availability checks."""

    def __init__(self, *, check_ttl_seconds: float = 30.0) -> None:
        self._tools: dict[str, ToolEntry] = {}
        self._check_cache: dict[str, tuple[bool, float]] = {}
        self._ttl = check_ttl_seconds

    # ── registration ────────────────────────────────────────

    def register(
        self,
        *,
        name: str,
        toolset: str,
        schema: dict[str, Any],
        handler: ToolHandler,
        check_fn: CheckFn | None = None,
        requires_env: tuple[str, ...] = (),
        max_result_size_chars: int = 32_000,
        description: str = "",
        override: bool = False,
    ) -> None:
        if name in self._tools and not override:
            raise ValueError(f"tool {name!r} already registered (pass override=True to replace)")
        self._tools[name] = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env,
            max_result_size_chars=max_result_size_chars,
            description=description,
        )
        # Bust cache on re-register.
        self._check_cache.pop(name, None)

    def deregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._check_cache.pop(name, None)

    # ── access ──────────────────────────────────────────────

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(
        self,
        *,
        toolset: str | None = None,
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in self._tools.values():
            if toolset is not None and entry.toolset != toolset:
                continue
            if not include_unavailable and not self._check_fn_cached(entry.name):
                continue
            out.append(entry.schema)
        return out

    # ── availability ────────────────────────────────────────

    def _check_fn_cached(self, name: str, *, now: float | None = None) -> bool:
        entry = self._tools.get(name)
        if entry is None:
            return False
        if entry.check_fn is None:
            return True
        ts = now if now is not None else time.monotonic()
        cached = self._check_cache.get(name)
        if cached is not None and (ts - cached[1]) < self._ttl:
            return cached[0]
        try:
            result = bool(entry.check_fn())
        except Exception:
            result = False
        self._check_cache[name] = (result, ts)
        return result

    def is_available(self, name: str) -> bool:
        return self._check_fn_cached(name)


# Process-global default registry. Tools register at import time against it.
_default_registry = ToolRegistry()


def default_registry() -> ToolRegistry:
    return _default_registry
