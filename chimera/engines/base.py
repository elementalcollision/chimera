"""Shared engine surface: result type + abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EngineResult:
    engine: str
    skipped: bool
    fired_at: str
    artifacts: list[str] = field(default_factory=list)
    api_call_count: int = 0
    summary: str = ""
    failure_reason: str | None = None


class EngineBase(ABC):
    """Common shape for Discovery / Curiosity / Reflection."""

    name: str

    @abstractmethod
    async def run(self, *, cycle: int) -> EngineResult:
        ...
