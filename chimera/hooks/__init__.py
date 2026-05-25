"""Git hooks shipped + installed by chimera (ADR 0141, Layer 3).

The pre-commit hook auto-logs chip-branch-jump events to
``mind/CHRONICLE.md`` without blocking commits. Installed via
``chimera doctor --install-hooks``.
"""

from .installer import (
    HOOK_SENTINEL,
    PRE_COMMIT_HOOK,
    InstallResult,
    install_pre_commit_hook,
)

__all__ = [
    "HOOK_SENTINEL",
    "PRE_COMMIT_HOOK",
    "InstallResult",
    "install_pre_commit_hook",
]
