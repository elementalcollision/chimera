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
import time
from pathlib import Path
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry
from .sandbox_env import sanitized_subprocess_env


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

# Shell wrappers an agent commonly (and wrongly) reaches for — `bash -c "..."`.
# The shell tool runs ONE binary as argv, so these never work; the rejection
# path gives a corrective hint instead of a bare refusal.
_SHELL_WRAPPERS: frozenset[str] = frozenset(
    {"bash", "sh", "zsh", "fish", "dash", "ksh", "csh", "tcsh"}
)

# Dev tools the project invokes via `uv run <tool>` rather than directly. When an
# agent reaches for one bare (e.g. `ruff` after dropping a `bash` wrapper), the
# rejection hints the `uv run` form so it self-corrects in one hop.
_UV_RUN_TOOLS: frozenset[str] = frozenset(
    {"ruff", "pytest", "mypy", "black", "pyright", "python", "pip", "chimera"}
)

# Modern search tools an agent reaches for that aren't installed/allow-listed
# (seen burning rounds in self-determination soaks: `rg` to scan a target file).
# Map each to its allow-listed POSIX equivalent so the agent self-corrects in
# one hop instead of retrying the blocked binary.
_SEARCH_TOOL_ALTERNATIVES: dict[str, str] = {
    "rg": "grep",
    "ag": "grep",
    "ack": "grep",
    "fd": "find",
    "fdfind": "find",
}


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
    # SECURITY BOUNDARY: ``.resolve()`` is load-bearing. It canonicalises
    # symlinks so a link planted inside mind/ or state/ that points outside
    # the roots (e.g. ``mind/escape -> /etc``) resolves to its real target
    # and then fails the containment check below. Do NOT replace this with a
    # lexical join (``os.path.normpath``) — that would follow the link name
    # without resolving it and reopen a symlink-traversal escape. The roots
    # are resolved too (see ``_allowed_roots``) so legitimately symlinked
    # roots (macOS /tmp, an operator-symlinked data dir) still compare equal.
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
        # Common agent mistake (seen across self-determination soaks): wrapping a
        # command in `bash -c "..."` / `sh -c "..."`. The shell tool runs ONE
        # binary directly — teach the correct argv form rather than just refusing,
        # so the agent self-corrects instead of burning rounds on blocked retries.
        if program in _SHELL_WRAPPERS:
            raise PermissionError(
                f"command {program!r} is not allowed: the shell tool executes a "
                f"single binary directly — it is NOT a shell, so `{program} -c "
                f'"..."` never works. Call the target binary as argv instead. '
                f'E.g. instead of {program} -c "ruff check --fix x.py", pass '
                f'argv=["uv", "run", "ruff", "check", "--fix", "x.py"]. For '
                f"pipes/redirection/&&, issue each step as a separate shell tool "
                f"call. Allowed binaries: {sorted(SAFE_COMMANDS)}"
            )
        # A dev tool the project runs via `uv run` (ruff, pytest, mypy, …). The
        # binary isn't on the allow-list, but `uv` is — so reaching for it bare
        # (the agent's next move after dropping `bash`) still fails. Hint the
        # `uv run` form so the agent reaches the working invocation in one hop.
        if program in _UV_RUN_TOOLS:
            raise PermissionError(
                f"command {program!r} is not directly allowed, but it runs via "
                f"`uv`: pass argv=[\"uv\", \"run\", {program!r}, ...] instead of "
                f"[{program!r}, ...]. E.g. argv=[\"uv\", \"run\", \"ruff\", "
                f'"check", "--fix", "<file>"]. Allowed binaries: {sorted(SAFE_COMMANDS)}'
            )
        # A modern search/find tool that isn't installed/allow-listed (rg, ag,
        # fd). The agent burns rounds retrying it; hint the POSIX equivalent that
        # IS on the allow-list so it self-corrects in one hop.
        if program in _SEARCH_TOOL_ALTERNATIVES:
            alt = _SEARCH_TOOL_ALTERNATIVES[program]
            raise PermissionError(
                f"command {program!r} is not installed/allowed. Use {alt!r} "
                f"instead — it IS on the allow-list. E.g. to search a file pass "
                f'argv=["grep", "-n", "<pattern>", "<file>"]; to find files pass '
                f'argv=["find", "<dir>", "-name", "<glob>"]. '
                f"Allowed binaries: {sorted(SAFE_COMMANDS)}"
            )
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

    # ADR 0151 validation lever (R5 forced-stall A/B). When
    # CHIMERA_SOAK_FORCE_STALL=1, refuse `git commit` UNCONDITIONALLY so a
    # commit-only phase can never converge and idles to max iterations — the
    # only way to deterministically exercise the prolonged stall under which
    # the planner/engines would spawn governance busywork (mechanism C). This
    # is a SOAK TEST KNOB, not a real gate: default off, and double-gated on
    # being inside a soak (CHIMERA_SOAK_RUN_ID set) so it can never fire on a
    # normal `chimera run`.
    if (
        program == "git"
        and len(argv) >= 2
        and argv[1] == "commit"
        and os.environ.get("CHIMERA_SOAK_FORCE_STALL") == "1"
        and os.environ.get("CHIMERA_SOAK_RUN_ID")
    ):
        raise PermissionError(
            "git commit blocked: CHIMERA_SOAK_FORCE_STALL=1 — the commit is "
            "intentionally unsatisfiable for the R5 forced-stall A/B test so "
            "phase 2 idles to max iterations. Not a real failure; nothing you "
            "do will make this commit land."
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

    # ADR 0146: pre-commit scope check (confabulation defense). Closes
    # the gap surfaced by v35 attempt #3 (PR #106): the agent committed
    # a fabricated diagnosis ~2 minutes after honestly committing
    # "I didn't do the work". Engine guards (scope_evasion,
    # degenerate_loop_abort, witness_rejected) detected it but could
    # not undo a commit that already landed. This is commit-time
    # enforcement — at the same chokepoint as the T0 gate above, so
    # both fire before subprocess.exec.
    #
    # Conservative refusal: missing design note / missing section /
    # ambiguous classification → warn-only. Override knob:
    # CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1.
    if program == "git" and len(argv) >= 2 and argv[1] == "commit":
        from chimera.core.scope_check import (
            ScopeCheckRefusal,
            check_commit_scope,
            commit_bypasses_index,
            resolve_repo_root,
        )
        # H1 (v42 fix): the pre-commit scope check inspects the STAGED index
        # (`git diff --cached`). A `git commit <pathspec>` / `-a` / `--amend`
        # commits files that never enter that snapshot, evading the
        # allowlist (v42 attempt #1 landed an off-charter tests/ file this
        # way). Refuse index-bypassing commit forms first so the scope check
        # below stays authoritative; force the auditable `git add` + bare
        # `git commit` flow. Same operator override as the scope check.
        bypass = commit_bypasses_index(argv)
        if bypass and not os.environ.get("CHIMERA_ALLOW_OFF_CHARTER_COMMIT"):
            raise PermissionError(
                f"git commit blocked (ADR 0146 / H1): {bypass}. The "
                "pre-commit scope check can only see staged files, so this "
                "form could evade the charter allowlist. Stage the allowed "
                "files explicitly (`git add <files>`) and run a bare "
                "`git commit -m \"...\"` instead.\n\n"
                "Override (operator-aware, single-use): "
                "export CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1"
            )
        try:
            check_commit_scope(resolve_repo_root(_resolve_cwd(args.get("cwd"))))
        except ScopeCheckRefusal as exc:
            raise PermissionError(
                f"git commit blocked by pre-commit scope check "
                f"(ADR 0146): {exc.result.reason}\n\n"
                "Override (operator-aware, single-use): "
                "export CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1"
            ) from exc

        # ADR 0162: in-loop critic gate — the LAST commit gate, judgment on top
        # of the deterministic scope/trust gates above. OFF unless
        # CHIMERA_CRITIC_ENFORCE=1 (so this is inert by default). It adjudicates
        # the staged change faithful before letting the commit land; a block
        # raises PermissionError with the concerns + the operator override, the
        # same shape as the scope-check refusal above.
        from chimera.core.critic_gate import check_commit_critic, enforce_enabled
        if enforce_enabled():
            decision = await check_commit_critic(
                resolve_repo_root(_resolve_cwd(args.get("cwd"))),
                goal=os.environ.get("CHIMERA_TASK_GOAL"),
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)

    # Resolve the program to a real path; reject if not found.
    resolved = shutil.which(program)
    if resolved is None:
        raise FileNotFoundError(f"program not found on PATH: {program}")

    cwd = _resolve_cwd(args.get("cwd"))

    timeout_s = float(args.get("timeout_s") or 10.0)
    timeout_s = min(max(timeout_s, 0.1), 60.0)

    # Local import (matches the scope_check pattern above) to keep the
    # tools→core dependency lazy and avoid any import-order coupling.
    from chimera.core.soak_ledger import record_test_run

    proc = await asyncio.create_subprocess_exec(
        resolved,
        *argv[1:],
        cwd=str(cwd),
        env=sanitized_subprocess_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Time the subprocess so the soak test-run ledger can record per-run
    # duration. perf_counter is monotonic. record_test_run is opt-in
    # (CHIMERA_SOAK_RUN_ID) and only fires for pytest invocations; it is
    # fail-soft, so it can never break a shell call.
    _t0 = time.perf_counter()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        record_test_run(
            argv=argv,
            exit_code=None,
            duration_ms=(time.perf_counter() - _t0) * 1000.0,
            stdout="",
            timed_out=True,
        )
        return f"$ {' '.join(argv)}\n[timeout after {timeout_s:.1f}s]"
    finally:
        # Kill any still-live child. ACT's per-phase budget wrapper
        # (asyncio.wait_for) cancels the phase coroutine when a cycle runs long;
        # that cancellation propagates into the awaited proc.communicate() as
        # CancelledError but does NOT kill the OS process. Without this, a
        # cancelled shell call — most often the pytest/uv gate run — orphans a
        # memory-heavy child; across the many cycles a soak battery drives, those
        # orphans pile up and exhaust memory (the 2026-06-16 testing-crash leak).
        # The TimeoutError branch already reaped; this covers CancelledError and
        # any other early exit. proc.kill() is synchronous (frees RSS at once);
        # the zombie is reaped by the loop's child watcher / on process exit.
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    duration_ms = (time.perf_counter() - _t0) * 1000.0
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    record_test_run(
        argv=argv,
        exit_code=proc.returncode,
        duration_ms=duration_ms,
        # pytest writes its pass/fail summary to stdout; combine stderr
        # so a crash traceback (often on stderr) is captured in the tail.
        stdout=out + ("\n" + err if err else ""),
        timed_out=False,
    )
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
