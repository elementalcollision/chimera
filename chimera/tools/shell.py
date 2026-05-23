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
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry


# The whitelist is intentionally small and read-only-ish at MVP.
# Concentric expansion (per ADR 0001) happens in later phases.
#
# v4.80: filter the advertised allow-list by what's actually on PATH.
# Soak v3 surfaced the model burning rounds when it called `rg` (in the
# raw list) but ripgrep wasn't installed — ACT raised FileNotFoundError
# and the model had to discover-and-retry. Trim the surface up front.
#
# v4.108 (soak v13): add `du`, `diff`, `sort`, `uniq`, `comm` — the
# specific commands soak v10 surfaced as missing during phase-2 work.
# All five are non-interactive POSIX utilities, read-only or
# bounded-write (none modify files without explicit destination
# flags), and standard on Linux/macOS. The wider "concentric ring"
# expansion (cp/mv/rm/tee/install/touch/etc.) the v13 agent proposed
# is deliberately NOT included here — that crosses a write-capability
# threshold that's an operator architecture decision, not a tactical
# allow-list addition. See ADR 0001 §"Tool sandbox" for the
# read-only-ish charter.
RAW_ALLOWLIST: frozenset[str] = frozenset(
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
        "sed",
        "awk",
        "rg",
        "find",
        "stat",
        "file",
        "which",
        "git",
        "mkdir",
        "python3",
        "test",
        "uv",
        # v4.108 — soak v10 surfaced
        "du",
        "diff",
        "sort",
        "uniq",
        "comm",
    }
)


def _resolved_allowlist() -> frozenset[str]:
    """Subset of RAW_ALLOWLIST whose programs are present on PATH."""
    return frozenset(cmd for cmd in RAW_ALLOWLIST if shutil.which(cmd) is not None)


# Resolved once at import time; the cost of re-checking shutil.which on
# every dispatch is wasted (PATH is effectively static in-process).
SAFE_COMMANDS: frozenset[str] = _resolved_allowlist()


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
                        "it defaults to the repo root, so relative paths 'state/x' "
                        "and 'mind/x' both resolve as expected. Absolute paths "
                        "outside the mind/state/repo-root tree are rejected."
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
    """Roots a shell subprocess may use as cwd.

    Always includes mind/ and state/. When they share a common parent
    (the typical layout: ``<repo>/mind`` and ``<repo>/state``), that
    parent is also allowed — without it, the model can't write to both
    'state/x' and 'mind/x' from a single cwd (L-2).
    """
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
    if roots[0].parent == roots[1].parent:
        roots.append(roots[0].parent)
    return roots


def _default_cwd() -> Path:
    """Default cwd for shell calls. Repo root when mind+state share one;
    otherwise mind. Picked so 'state/x' and 'mind/x' both resolve.
    """
    roots = _allowed_roots()
    return roots[2] if len(roots) >= 3 else roots[0]


def _resolve_cwd(cwd_arg: str | None) -> Path:
    roots = _allowed_roots()
    base = _default_cwd()
    if cwd_arg is None:
        return base
    candidate = Path(cwd_arg)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
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


def _current_trust_tier_is_T0() -> bool:
    """Fail-open trust-tier check for the commit gate.

    Reads ``trust_state.json`` from ``$CHIMERA_STATE_DIR`` (or ``state/``)
    and returns True only when ``current_tier == 0``. Any read / parse
    failure returns False so a missing or malformed state file cannot
    accidentally block boot or first-run.
    """
    state_dir = os.environ.get("CHIMERA_STATE_DIR")
    base = Path(state_dir) if state_dir else Path.cwd() / "state"
    path = base / "trust_state.json"
    try:
        data = json.loads(path.read_text())
        return int(data.get("current_tier", -1)) == 0
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return False


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

    # Soak v20 finding: when engines are off (investigation-only phase),
    # a phase-1 git commit poisons the branch diff and prevents the
    # soft-sentinel exit from firing once phase 2 lands its
    # implementation commit. Block commit/push unconditionally in that
    # mode — the env var is the contract.
    if (
        program == "git"
        and os.environ.get("CHIMERA_ENGINES_ENABLED") == "0"
        and len(argv) >= 2
        and argv[1] in ("commit", "push")
    ):
        raise PermissionError(
            f"git {argv[1]} blocked: CHIMERA_ENGINES_ENABLED=0 "
            "(investigation-only phase). Commits during phase 1 "
            "poison the branch diff and prevent the soft-sentinel "
            "from firing in phase 2."
        )

    # v4.117 (ADR 0117): trust-state commit gate. Soak v20-3rd surfaced
    # the platform gap: when v4.115 fires repeatedly across cycles, the
    # demotions collapse trust to T0 but nothing prevents the *next*
    # commit from re-tripping the same detector. Trust demotion is a
    # punishment, not a prevention. Block git commit/push at T0 until
    # the operator promotes the agent. Parallel layer to the engines-off
    # gate above; both must be passed before the call reaches subprocess.
    if (
        program == "git"
        and len(argv) >= 2
        and argv[1] in ("commit", "push")
        and _current_trust_tier_is_T0()
    ):
        raise PermissionError(
            f"git {argv[1]} blocked: trust state is T0 "
            "(cumulative detector firings have collapsed trust). "
            "Operator must promote the agent before further commits."
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
