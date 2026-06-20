"""Foreign-repo context block for a multi-repo soak (ADR 0186 B.3b).

When the agent works on a FOREIGN repo it must reason about the *target* repo,
not chimera. B.3a gave it a neutral system-prompt voice; B.3b gives it the
concrete context the ADR calls for — the target repo's own README/docs and the
current (failing) ``verify_cmd`` output — assembled into a markdown block the
soak appends to the foreign INBOX.

This module is pure/offline: it reads a README from the cloned worktree and
formats a string. It does NOT execute the foreign ``verify_cmd`` (the soak runs
the gate and passes its captured output in) — so the formatting logic stays
unit-testable and free of untrusted-code execution (that surface is the soak's,
hardened by the ADR 0186 B.4 sandbox).
"""

from __future__ import annotations

from pathlib import Path

#: README filenames probed in priority order (first existing match wins).
_README_CANDIDATES: tuple[str, ...] = (
    "README.md",
    "README.rst",
    "README.txt",
    "README",
    "docs/README.md",
)


def repo_readme_excerpt(worktree: Path, *, max_chars: int = 4000) -> tuple[str, str]:
    """Return ``(relpath, excerpt)`` for the target repo's README, or ``("", "")``.

    Probes ``_README_CANDIDATES`` under ``worktree`` and returns the first that
    exists, truncated to ``max_chars`` (on a line boundary, with an ellipsis
    marker when truncated). Unreadable files are skipped, not raised.
    """
    for rel in _README_CANDIDATES:
        path = worktree / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0].rstrip()
            text += "\n…[README truncated]"
        return rel, text.strip()
    return "", ""


def _gate_output_tail(gate_output: str, *, max_lines: int = 40) -> str:
    """The last ``max_lines`` non-empty-trimmed lines of the captured gate output."""
    lines = (gate_output or "").rstrip().splitlines()
    if len(lines) > max_lines:
        lines = ["…[earlier gate output trimmed]", *lines[-max_lines:]]
    return "\n".join(lines).strip()


def foreign_context_block(
    worktree: Path,
    repo: str,
    gate_cmd: str,
    gate_output: str,
    *,
    readme_max_chars: int = 4000,
    gate_tail_lines: int = 40,
) -> str:
    """Assemble the foreign-repo context appendix for the INBOX (ADR 0186 B.3b).

    Includes the target repo's README excerpt (if any) and the current
    (failing) gate output, framed for an agent that did not write the repo.
    Always returns a non-empty block (the gate section is always present); the
    README section is omitted when no README is found.
    """
    parts: list[str] = [f"## Repository context — `{repo}`", ""]

    relpath, excerpt = repo_readme_excerpt(worktree, max_chars=readme_max_chars)
    if excerpt:
        parts.append(f"### `{relpath}` (excerpt)")
        parts.append("")
        parts.append(excerpt)
        parts.append("")
    else:
        parts.append("_(no README found in the repository root)_")
        parts.append("")

    tail = _gate_output_tail(gate_output, max_lines=gate_tail_lines)
    parts.append(f"### Current gate output — `{gate_cmd}`")
    parts.append("")
    parts.append("This command is currently RED; your job is to make it pass.")
    parts.append("")
    parts.append("```")
    parts.append(tail if tail else "(no output captured)")
    parts.append("```")
    return "\n".join(parts)
