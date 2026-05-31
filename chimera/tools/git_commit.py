"""Atomic `git_commit` tool (R4 / ADR 0150).

Why this exists. The v46 commit-phase arc (ADR 0147 detector → ADR 0148 harness
commit) and the analysis in
`mind/research/why-the-agent-avoids-git-commit-2026-05-30.md` established that
the agent reliably authors + stages + greens a deliverable but does NOT issue a
bare `git commit` — it self-reports done while staged-but-uncommitted (staging ≈
done), treats the heavily-gated commit as risky, and substitutes meta-work. The
single most effective counter, per the agent's own research, is to collapse the
commit ritual into ONE blessed affordance: a single tool call that stages the
named paths, commits, and returns the new HEAD.

This tool does NOT bypass any commit gate. It routes the actual `git add` /
`git commit` through :func:`chimera.tools.shell.shell_handler`, so the
engines-off block, the T0 trust gate, and the ADR 0146 pre-commit scope check
ALL still fire exactly as they do for a hand-issued `git commit`. The only thing
it removes is the agent's ability to *skip* the commit step:

- ATTACKS "staging ≈ done" — the tool's success IS the commit; there is no
  staged-but-uncommitted intermediate to mistake for completion.
- ATTACKS gate-induced risk aversion — the gated complexity sits behind one
  obviously-blessed call rather than a free-form shell incantation.
- ATTACKS single-shot under-execution — one tool call completes the whole
  ritual (stage → commit → verify HEAD), so the agent's one-action-then-stop
  tendency now *lands* the commit instead of stopping at a read.
"""

from __future__ import annotations

from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry
from .shell import shell_handler

GIT_COMMIT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "git_commit",
        "description": (
            "Atomically stage the given paths (if any) and create ONE git "
            "commit, then return the new HEAD. Use this to commit your work — "
            "it is the single, complete commit step (do NOT also run a bare "
            "`git commit` via shell). The message is auto-prefixed with the "
            "`[agent]` marker if you omit it. All commit gates (scope check, "
            "trust, phase) still apply; a refusal is returned as text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": (
                        "Commit message. Auto-prefixed with `[agent] ` if it "
                        "does not already start with `[agent]`."
                    ),
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional paths to `git add` before committing. Omit "
                        "to commit whatever is already staged."
                    ),
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory (defaults to repo root).",
                },
            },
            "required": ["message"],
        },
    },
}


def _normalize_message(message: str) -> str:
    """Ensure the message carries the `[agent]` autonomous-delivery marker."""
    msg = message.strip()
    return msg if msg.startswith("[agent]") else f"[agent] {msg}"


async def git_commit_handler(args: dict[str, Any], context: DispatchContext) -> str:
    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("git_commit requires a non-empty 'message'")
    message = _normalize_message(message)

    raw_paths = args.get("paths") or []
    if not isinstance(raw_paths, list) or not all(isinstance(p, str) for p in raw_paths):
        raise ValueError("git_commit 'paths' must be a list of strings")
    cwd = args.get("cwd")

    # 1. Stage the explicit deliverables (auditable `git add` — the form the
    #    ADR 0146 index-scope check requires). Routed through shell_handler so
    #    the allow-list applies.
    if raw_paths:
        add_argv = ["git", "add", "--", *raw_paths]
        await shell_handler({"argv": add_argv, "cwd": cwd}, context)

    # 2. Bare `git commit -m <message>` — routed through the SAME gated path a
    #    hand-issued commit takes. A gate refusal raises PermissionError; we
    #    surface its reason to the agent verbatim instead of crashing the turn,
    #    so the agent learns *why* (e.g. scope-check refusal) and can correct.
    try:
        await shell_handler(
            {"argv": ["git", "commit", "-m", message], "cwd": cwd}, context,
        )
    except PermissionError as exc:
        return f"git_commit refused by a commit gate (not committed):\n{exc}"

    # 3. Confirm + return the new HEAD so the tool's success is unambiguous —
    #    no staged-but-uncommitted ambiguity.
    head = await shell_handler(
        {"argv": ["git", "log", "-1", "--format=%h %s"], "cwd": cwd}, context,
    )
    head_line = ""
    for line in head.splitlines():
        line = line.strip()
        if line and not line.startswith("$ ") and not line.startswith("[exit="):
            head_line = line
            break
    return f"committed: {head_line}" if head_line else "committed."


def register_git_commit_tool(registry: ToolRegistry | None = None) -> None:
    """Idempotent: register the git_commit tool against the given (or default) registry."""
    reg = registry or default_registry()
    reg.register(
        name="git_commit",
        toolset="core",
        schema=GIT_COMMIT_SCHEMA,
        handler=git_commit_handler,
        description="Atomically stage + commit + return HEAD (gated).",
        override=True,
    )
