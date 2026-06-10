"""ADR 0141 Layer 3 — pre-commit hook installer.

Idempotent installer for a pure-bash ``pre-commit`` git hook that
auto-logs chip-branch-jump events to ``mind/CHRONICLE.md``. Does NOT
block commits; only records evidence (blocking legitimate operator
commits would be hostile).

The hook is identified by a sentinel marker line. Second install is a
no-op; an existing foreign hook is never clobbered.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path


HOOK_SENTINEL = "# chimera-pre-commit-hook v1"

PRE_COMMIT_HOOK = f"""#!/bin/sh
{HOOK_SENTINEL}
# Chip-branch-jump detector (ADR 0141, Layer 3). Logs to mind/CHRONICLE.md
# when a commit lands in the main worktree on a non-main branch.
# Never blocks the commit — evidence-recording only.

set -e

toplevel="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$toplevel" ]; then
  exit 0
fi

# Only act when invoked from the toplevel (= main worktree). Sibling
# worktrees have their own toplevel and are NOT the papercut.
hook_dir="$(cd "$(dirname "$0")" && pwd)"
expected_hook_dir="$toplevel/.git/hooks"
if [ "$hook_dir" != "$expected_hook_dir" ]; then
  exit 0
fi

branch="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [ -z "$branch" ] || [ "$branch" = "main" ]; then
  exit 0
fi

chronicle="$toplevel/mind/CHRONICLE.md"
mkdir -p "$(dirname "$chronicle")"

author="$(git config user.email 2>/dev/null || echo unknown)"
ts="$(date -u +'%Y-%m-%d %H:%M:%S')"

{{
  printf '\\n## %s — chip-branch-jump detected at commit time\\n\\n' "$ts"
  printf '**Event**: pre-commit hook fired\\n'
  printf '**Worktree**: %s (= git toplevel)\\n' "$toplevel"
  printf '**Branch**: %s\\n' "$branch"
  printf '**Commit author**: %s\\n' "$author"
  printf '**Mitigation**: this commit landed but the chip-branch-jump is recorded for audit.\\n'
  printf '**See**: ADR 0114, PR #46 (Layer 1), ADR 0141 (Layers 2+3).\\n'
}} >> "$chronicle"

exit 0
"""


@dataclass(frozen=True)
class InstallResult:
    status: str  # "installed" | "already_installed" | "foreign_hook" | "no_git_dir"
    path: Path | None
    message: str


def install_pre_commit_hook(repo_root: Path) -> InstallResult:
    """Install the pre-commit hook at ``<repo_root>/.git/hooks/pre-commit``.

    Idempotent: a second call on an already-installed hook returns
    ``already_installed`` without rewriting. Never overwrites a foreign
    hook (returns ``foreign_hook``).
    """
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        return InstallResult(
            "no_git_dir", None,
            f"{git_dir} is not a directory; not a git repo or uses gitdir-file worktree",
        )

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        try:
            existing = hook_path.read_text(encoding="utf-8")
        except OSError as exc:
            return InstallResult(
                "foreign_hook", hook_path,
                f"existing hook at {hook_path} cannot be read ({exc}); not clobbering",
            )
        if HOOK_SENTINEL in existing:
            return InstallResult(
                "already_installed", hook_path,
                f"chimera pre-commit hook already installed at {hook_path}",
            )
        return InstallResult(
            "foreign_hook", hook_path,
            f"foreign pre-commit hook at {hook_path} (no chimera sentinel); "
            "will not clobber. Remove it manually or merge our hook content "
            "(see chimera.hooks.installer.PRE_COMMIT_HOOK) before re-running.",
        )

    hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
    # chmod +x — preserve existing umask bits, just add x for user/group/other
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return InstallResult(
        "installed", hook_path,
        f"installed chimera pre-commit hook at {hook_path}",
    )
