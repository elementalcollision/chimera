"""Code execution tool — Python subprocess with resource limits.

Per ADR 0001 §"Tool sandbox" + ADR 0001 §"Concentric tool surface" (ring 3).

The subprocess runs ``python -I`` (isolated mode — no PYTHONPATH, no site
packages) on a tempfile under the mind directory. POSIX resource limits
cap memory and CPU. Network access is NOT currently blocked at the OS
level — see TODO below.

Safety posture (MVP):
- ``cwd`` restricted to ``$CHIMERA_MIND_DIR`` or ``$CHIMERA_STATE_DIR``.
- ``RLIMIT_AS`` caps virtual memory at 256MB (POSIX only).
- ``RLIMIT_CPU`` caps CPU time (POSIX only).
- ``asyncio.wait_for`` enforces wall-clock timeout (default 5s, max 30s).
- ``python -I`` ignores ``PYTHONPATH``, ``PYTHON*`` env, and the user site.

TODO: Network egress isolation. Full sandboxing requires unshare/seccomp
or a Docker-in-Docker pattern. Tracked as a follow-up ADR.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry

try:  # POSIX only — fine inside the Chimera Linux container.
    import resource as _resource  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — POSIX-only path
    _resource = None


CODE_EXEC_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "code_exec",
        "description": (
            "Run a short, single-file Python snippet in a sandboxed subprocess. "
            "Uses Python's isolated mode (-I): no PYTHONPATH, no user site. "
            "Memory capped at 256MB, CPU + wall-clock bounded by timeout_s (default 5s, "
            "max 30s). Cwd is under the mind/state roots. Use this to test ideas, "
            "compute, or transform files — NOT for long-running services."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute. Output goes to stdout/stderr.",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Hard wall-clock timeout in seconds (default 5, max 30).",
                },
                "cwd": {
                    "type": "string",
                    "description": (
                        "Working directory. Must be under $CHIMERA_MIND_DIR or "
                        "$CHIMERA_STATE_DIR. Defaults to mind dir."
                    ),
                },
            },
            "required": ["code"],
        },
    },
}


def _allowed_roots() -> list[Path]:
    roots: list[Path] = []
    mind = os.environ.get("CHIMERA_MIND_DIR")
    state = os.environ.get("CHIMERA_STATE_DIR")
    roots.append(Path(mind).resolve() if mind else (Path.cwd() / "mind").resolve())
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
            f"cwd {candidate} is outside allowed roots ({', '.join(str(r) for r in roots)})"
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


def _build_preexec(timeout_s: float):
    """Return a preexec_fn that applies POSIX rlimits, or None on non-POSIX."""
    if _resource is None:
        return None

    def _apply_limits() -> None:
        # Virtual address space cap (256MB).
        try:
            _resource.setrlimit(
                _resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)
            )
        except (ValueError, OSError):
            pass
        # CPU time cap — soft = timeout, hard = timeout + 1.
        try:
            cpu_s = max(1, int(timeout_s) + 1)
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        except (ValueError, OSError):
            pass

    return _apply_limits


async def code_exec_handler(args: dict[str, Any], context: DispatchContext) -> str:
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")
    timeout_s = float(args.get("timeout_s") or 5.0)
    timeout_s = min(max(timeout_s, 0.1), 30.0)
    cwd = _resolve_cwd(args.get("cwd"))

    # Write the snippet to a tempfile under cwd so paths in the code work.
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        dir=str(cwd),
        encoding="utf-8",
    ) as f:
        f.write(code)
        script_path = Path(f.name)

    try:
        preexec = _build_preexec(timeout_s)
        kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if preexec is not None:
            kwargs["preexec_fn"] = preexec
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(script_path), **kwargs
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"$ python -I {script_path.name}\n[timeout after {timeout_s:.1f}s]"
    finally:
        script_path.unlink(missing_ok=True)

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    parts = [f"$ python -I {script_path.name}"]
    if out:
        parts.append(out.rstrip())
    if err:
        parts.append(f"[stderr]\n{err.rstrip()}")
    parts.append(f"[exit={proc.returncode}]")
    return "\n".join(parts)


def register_code_exec_tool(registry: ToolRegistry | None = None) -> None:
    reg = registry or default_registry()
    reg.register(
        name="code_exec",
        toolset="core",
        schema=CODE_EXEC_SCHEMA,
        handler=code_exec_handler,
        description="Sandboxed Python subprocess.",
        override=True,
    )
