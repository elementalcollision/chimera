"""Write-intent detection + path extraction + Path A3 rewrite.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)":

- ``requires_write_intent(task_text)`` — does the task mention writing,
  editing, appending, creating?
- ``extract_target_paths(task_text)`` — what files does the task expect
  to land in?
- Path A3 rewrite — bare ``foo.md`` (no path separator) is rewritten to
  ``mind/foo.md`` per Reggio's mind-as-default convention.

These are the inputs to PR #58 escalation (see :mod:`chimera.core.escalation`)
and PR #54 silent-failure detection.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Write verbs that imply the task expects file mutation.
_WRITE_VERBS = (
    "append",
    "write",
    "edit",
    "update",
    "create",
    "add",
    "patch",
    "modify",
    "replace",
    "insert",
    "save",
)

_VERB_PATTERN = r"\b(?:" + "|".join(_WRITE_VERBS) + r")\b"
_WRITE_VERB_RE = re.compile(_VERB_PATTERN, re.IGNORECASE)

# A file path token: optional dir segments separated by `/`, then a name
# with one of our recognized extensions. Both bare (`foo.md`) and prefixed
# (`mind/foo.md`, `state/x/y.json`) forms match.
_PATH_RE = re.compile(
    r"\b((?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+\.(?:md|json|ya?ml|txt|py|toml|sql))\b"
)

# Roots that signal "already prefixed" — leave them alone.
_KNOWN_ROOTS = frozenset({"mind", "state", "docs", "tests", "chimera", "research"})


def requires_write_intent(task_text: str) -> bool:
    """True iff the task text contains a write verb."""
    return bool(_WRITE_VERB_RE.search(task_text))


def _apply_a3_rewrite(path: str) -> str:
    """Bare names (no `/`) get the `mind/` prefix; known roots pass through."""
    if "/" not in path:
        return f"mind/{path}"
    head = path.split("/", 1)[0]
    if head in _KNOWN_ROOTS:
        return path
    # Path starts with something else (e.g. `tmp/foo.md`) — leave it; rely
    # on shell-tool cwd enforcement to reject if it's out of bounds.
    return path


def extract_target_paths(task_text: str) -> list[str]:
    """Return the unique, A3-rewritten paths the task implies."""
    paths: list[str] = [m.group(1) for m in _PATH_RE.finditer(task_text)]
    rewritten = [_apply_a3_rewrite(p) for p in paths]
    # Stable dedup.
    return list(dict.fromkeys(rewritten))


def silent_failure(task_text: str, write_targets: Iterable[str]) -> bool:
    """PR #54: write-intent task that produced zero write targets is a silent failure."""
    if not requires_write_intent(task_text):
        return False
    return not list(write_targets)


def write_intent_satisfied(
    task_text: str,
    write_targets: Iterable[str],
) -> bool:
    """True iff every extracted target appears in the actual write_targets.

    The ACT phase records each completed write under its actual path; the
    guard compares that set against the paths the task implied.
    """
    expected = set(extract_target_paths(task_text))
    if not expected:
        return True
    actual = {_apply_a3_rewrite(p) for p in write_targets}
    return expected.issubset(actual)
