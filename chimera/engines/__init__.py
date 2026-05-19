"""Daily engines — Discovery / Curiosity / Reflection.

Per ADR 0003 deferred-list, promoted to v1.1.

Each engine runs at most once per UTC day, gated by the
:class:`EngineScheduler`. Engines write narrative to ``mind/CHRONICLE.md``
(idempotent per-day sections) and project artifacts to ``mind/wiki/``.
"""

from .base import EngineResult, EngineBase
from .chronicle import ChronicleManager
from .curiosity import CuriosityEngine
from .discovery import DiscoveryEngine
from .reflection import ReflectionEngine
from .scheduler import EngineScheduler

__all__ = [
    "ChronicleManager",
    "CuriosityEngine",
    "DiscoveryEngine",
    "EngineBase",
    "EngineResult",
    "EngineScheduler",
    "ReflectionEngine",
]
