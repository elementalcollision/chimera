"""Shell tool — strict allow-list, no shell interpretation.

Per ADR 0001 §"Tool sandbox" + ADR 0003 §"ACT-phase guards":

- argv-only invocation (no shell metacharacters — no pipes, no redirects)
- First token (program) must be in :data:`SAFE_COMMANDS` UNLESS the
  dispatch context has ``elevated=True``
- Timeout-bounded subprocess
- Result truncated by the dispatcher per ``max_result_size_chars``

For MVP the cwd defaults to the mind directory; explicit cwd must resolve
under ``$CHIMERA_MIND_DIR`` or ``$CHIMERA_STATE_DIR`` (or absolute paths
within them). Anything else is rejected.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry


# The whitelist is intentionally small and read-only-ish at MVP.
# Concentric expansion (per ADR 0001) happens in later phases.
SAFE_COMMANDS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "echo",
        "pwd",
        "date",
        "grep",
        "rg",
        "find",
        "stat",
        "file",
        "which",
    }
)


SHELL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": (
            "Execute a vetted, non-interactive shell command. Provide argv as a list "
            "of strings (NO shell metacharacters — no pipes, no redirects, no globbing). "
            "First token must be in the allow-list unless the session is elevated. "
            f"Allow-list: {sorted(SAFE_COMMANDS)}. "
            "Use this for read-only inspection of /mind and /state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argv tokens; argv[0] is the program.",
                },
                "cwd": {
                    "type": "string",
                    "description": (
                        "Optional working directory. PREFER OMITTING this field — "
                        "it defaults to the mind directory. If you set it, use a "
                        "RELATIVE path like 'state' or 'mind/wiki', NOT an absolute "
                        "path. Absolute paths outside the mind/state roots are "
                        "rejected."
                    ),
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Hard timeout in seconds (default 10, max 60).",
                },
            },
            "required": ["argv"],
        },
    },
}


def _allowed_roots() -> list[Path]:
    roots: list[Path] = []
    mind = os.environ.get("CHIMERA_MIND_DIR")
    state = os.environ.get("CHIMERA_STATE_DIR")
    if mind:
        roots.append(Path(mind).resolve())
    else:
        roots.append((Path.cwd() / "mind").resolve())
    if state:
        roots.append(Path(state).resolve())
    else:
        roots.append((Path.cwd() / "state").resolve())
    return roots


def _resolve_cwd(cwd_arg: str | None) -> Path:
    roots = _allowed_roots()
    if cwd_arg is None:
        return roots[0]
    candidate = Path(cwd_arg)
    if not candidate.is_absolute():
        candidate = (roots[0] / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not any(_is_relative_to(candidate, r) for r in roots):
        raise ValueError(
            f"cwd {candidate} is outside allowed roots. "
            f"Use a RELATIVE path like 'state' or 'mind', or omit cwd entirely. "
            f"Allowed absolute roots: {', '.join(str(r) for r in roots)}"
        )
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError(f"cwd {candidate} does not exist or is not a directory")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


async def shell_handler(args: dict[str, Any], context: DispatchContext) -> str:
    argv = args.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ValueError("argv must be a non-empty list of strings")
    if not all(isinstance(t, str) for t in argv):
        raise ValueError("argv must be a list of strings")

    program = argv[0]
    if program not in SAFE_COMMANDS and not context.elevated:
        raise PermissionError(
            f"command {program!r} not in shell allow-list "
            f"(set context.elevated=True to bypass; allow-list: {sorted(SAFE_COMMANDS)})"
        )

    # Resolve the program to a real path; reject if not found.
    resolved = shutil.which(program)
    if resolved is None:
        raise FileNotFoundError(f"program not found on PATH: {program}")

    cwd = _resolve_cwd(args.get("cwd"))

    timeout_s = float(args.get("timeout_s") or 10.0)
    timeout_s = min(max(timeout_s, 0.1), 60.0)

    proc = await asyncio.create_subprocess_exec(
        resolved,
        *argv[1:],
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"$ {' '.join(argv)}\n[timeout after {timeout_s:.1f}s]"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    parts = [f"$ {' '.join(argv)}"]
    if out:
        parts.append(out.rstrip())
    if err:
        parts.append(f"[stderr]\n{err.rstrip()}")
    parts.append(f"[exit={proc.returncode}]")
    return "\n".join(parts)


def register_shell_tool(registry: ToolRegistry | None = None) -> None:
    """Idempotent: register the shell tool against the given (or default) registry."""
    reg = registry or default_registry()
    reg.register(
        name="shell",
        toolset="core",
        schema=SHELL_SCHEMA,
        handler=shell_handler,
        description="Vetted shell exec with strict allow-list.",
        override=True,
    )
