"""Soak-run instrumentation ledgers (R3 build-capability prerequisite).

Background
----------
Through v39 every soak was an **R1** charter (classify / diagnose /
document) — the autonomous loop never authored code that landed in
main. The v40→v43 build-capability ladder (see
``mind/research/v40-build-mind-count-design.md``) is the first time
Chimera's ACT phase is asked to *build*. To evaluate the
verdict-honesty gate on those soaks we need a post-hoc record of how
hard the agent actually worked: how many ACT cycles, how many tool
calls, which tools, and (in the sibling :mod:`test-run ledger`) which
test invocations ran and with what exit code.

This module emits the **ACT-phase tool-call ledger**. It is
deliberately opt-in: it writes nothing unless ``CHIMERA_SOAK_RUN_ID``
is set in the environment. A normal ``chimera run`` therefore behaves
byte-for-byte as before; only a soak runner that exports the run id
produces ledger files. This mirrors the env-knob discipline used
elsewhere in the codebase (e.g. ``CHIMERA_ADAPTIVE_TOPK_TEMPORAL``).

Layout
------
``<mind_dir>/soak/<run-id>/act-tools.jsonl`` — one JSON object per
``ActExecutor.execute()`` call (i.e. one record per ACT cycle × task).
The record groups the full tool-call sequence for that execute, so
``act_cycles`` for a postmortem is simply the line count and the
per-cycle tool histogram is reconstructable without re-running.

Why args are hashed, not stored
--------------------------------
Tool arguments can be large (file contents in a write) or noisy. The
ledger stores a stable 12-char SHA-256 prefix of the canonical args
JSON instead of the raw args: enough to detect "same call repeated"
(the degenerate-loop signal) and to correlate across cycles, without
bloating the ledger or leaking large payloads into ``mind/``.

Fail-soft contract
------------------
Instrumentation must never break a soak. Every public function here
swallows its own errors and returns ``None`` on failure — a missing
directory, an unwritable path, or a malformed record degrades to "no
ledger line", never to an exception that propagates into the loop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .act import ActResult

_RUN_ID_ENV = "CHIMERA_SOAK_RUN_ID"

# Run ids land in a filesystem path, so constrain them to a safe charset.
# Anything outside is collapsed to '-' so a hostile/typo'd value cannot
# escape the soak directory (no slashes, no '..').
_SAFE_RUN_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")

ACT_TOOLS_FILENAME = "act-tools.jsonl"
TEST_RUNS_FILENAME = "test-runs.jsonl"

# Cap the stored task text so a giant INBOX line can't bloat the ledger.
_TASK_PREVIEW_CHARS = 200

# How many trailing stdout lines a test-run record retains. Enough to
# capture pytest's summary line ("N passed, M failed") plus a short
# traceback tail, without storing whole logs in mind/.
_STDOUT_TAIL_LINES = 20

_MIND_DIR_ENV = "CHIMERA_MIND_DIR"
# Interpreters that run a test module via ``-m pytest``.
_PY_INTERPRETERS = frozenset({"python", "python3", "py"})
# Runners that invoke pytest as a sub-argument (e.g. ``uv run pytest``,
# ``uv run --extra dev pytest``, ``uv run python -m pytest``). The v40
# build soak runs the gate through ``uv run`` (PR #141), so the ledger
# must recognize pytest anywhere in a runner's argv tail.
_TEST_RUNNERS = frozenset({"uv", "uvx", "poetry", "hatch", "pdm", "rye"})


def default_mind_dir() -> Path:
    """Resolve the mind dir the same way ``ChimeraLoop`` does.

    The shell handler has no ``config`` object, so test-run records
    resolve their target from ``CHIMERA_MIND_DIR`` (default ``mind``) —
    identical to ``LoopConfig``'s default.
    """
    return Path(os.environ.get(_MIND_DIR_ENV, "mind"))


def is_test_command(argv: list[str]) -> bool:
    """True if ``argv`` invokes pytest.

    Matches a bare ``pytest`` program and ``python -m pytest`` (any
    interpreter in :data:`_PY_INTERPRETERS`). Deliberately narrow: only
    pytest counts as a "test run" for the verdict-honesty cross-check,
    so a stray ``python script.py`` is not logged here (it still lands
    in the ACT tool-call ledger).
    """
    if not argv:
        return False
    program = Path(argv[0]).name  # tolerate an absolute path in argv[0]
    if program == "pytest":
        return True
    if program in _PY_INTERPRETERS and "pytest" in argv[1:]:
        return True
    # Runner-wrapped: ``uv run [--extra dev] pytest …`` / ``uv run python
    # -m pytest …``. The gate command runs through `uv run`, so pytest
    # appears as a sub-argument, not argv[0]. Match it anywhere in the
    # tail. (`pytest` as a bare token only ever names the runner here;
    # it would not appear as a flag value.)
    if program in _TEST_RUNNERS and "pytest" in argv[1:]:
        return True
    return False


def soak_run_id() -> str | None:
    """Return the sanitized soak run id, or ``None`` when not in a soak.

    The ledger is opt-in: absent ``CHIMERA_SOAK_RUN_ID`` (or an empty /
    whitespace-only value) this returns ``None`` and all emit functions
    become no-ops.
    """
    raw = os.environ.get(_RUN_ID_ENV)
    if raw is None:
        return None
    cleaned = _SAFE_RUN_ID_RE.sub("-", raw.strip())
    # Collapse any run of dots so no ".." parent-ref segment survives,
    # even though the charset filter above already removed separators.
    cleaned = re.sub(r"\.{2,}", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned or None


def soak_ledger_dir(mind_dir: Path | str, run_id: str | None = None) -> Path | None:
    """Return ``<mind_dir>/soak/<run-id>``, or ``None`` when not in a soak.

    Does not create the directory; see :func:`record_act_tools`.
    """
    rid = run_id if run_id is not None else soak_run_id()
    if not rid:
        return None
    return Path(mind_dir) / "soak" / rid


def args_hash(args: dict[str, Any]) -> str:
    """Stable 12-char SHA-256 prefix of canonical args JSON.

    ``sort_keys`` + ``default=str`` make this deterministic across runs
    and tolerant of non-JSON-native values (Paths, etc.).
    """
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_act_record(
    *,
    run_id: str,
    cycle: int,
    task_text: str,
    result: ActResult,
) -> dict[str, Any]:
    """Build the JSON record for one ACT ``execute()`` call.

    Kept pure (no I/O) so it is trivially unit-testable.
    """
    tool_calls = [
        {
            "name": call.name,
            "args_hash": args_hash(call.args),
            # Per-call outcome, populated post-dispatch by ActExecutor.
            # ``is_error`` is None for any call in a batch that aborted
            # before dispatch (degenerate-loop / ping-pong); ``duration_ms``
            # is the wall-clock the dispatch spent.
            "is_error": call.is_error,
            "duration_ms": call.duration_ms,
        }
        for call in result.tool_call_history
    ]
    # Aggregate per-cycle outcome rollups so a postmortem can read
    # "this ACT cycle made N calls, E of them errored, taking T ms"
    # without re-parsing the per-call list.
    error_count = sum(1 for c in tool_calls if c["is_error"] is True)
    total_ms = round(
        sum(c["duration_ms"] for c in tool_calls if c["duration_ms"] is not None),
        3,
    )
    return {
        "run_id": run_id,
        "cycle": cycle,
        "task": task_text[:_TASK_PREVIEW_CHARS],
        "finish_reason": result.finish_reason,
        "completed": bool(result.completed),
        "rounds": result.rounds,
        "api_call_count": result.api_call_count,
        "tool_call_count": len(tool_calls),
        "tool_error_count": error_count,
        "tool_total_ms": total_ms,
        "tool_calls": tool_calls,
        "ts": round(time.time(), 3),
    }


def record_act_tools(
    *,
    mind_dir: Path | str,
    cycle: int,
    task_text: str,
    result: ActResult,
) -> Path | None:
    """Append one ACT-cycle record to the tool-call ledger.

    No-op (returns ``None``) when ``CHIMERA_SOAK_RUN_ID`` is unset.
    Fail-soft: any I/O or serialization error is swallowed and returns
    ``None`` so instrumentation never breaks a soak.
    """
    rid = soak_run_id()
    if not rid:
        return None
    ledger_dir = soak_ledger_dir(mind_dir, rid)
    if ledger_dir is None:
        return None
    try:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        record = build_act_record(
            run_id=rid, cycle=cycle, task_text=task_text, result=result
        )
        path = ledger_dir / ACT_TOOLS_FILENAME
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return path
    except Exception:  # noqa: BLE001 - fail-soft by contract
        return None


def _stdout_tail(stdout: str) -> list[str]:
    """Last :data:`_STDOUT_TAIL_LINES` non-empty stdout lines."""
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    return lines[-_STDOUT_TAIL_LINES:]


def build_test_run_record(
    *,
    run_id: str,
    argv: list[str],
    exit_code: int | None,
    duration_ms: float,
    stdout: str = "",
    timed_out: bool = False,
) -> dict[str, Any]:
    """Build the JSON record for one test (pytest) subprocess. Pure."""
    return {
        "run_id": run_id,
        "argv": list(argv),
        "program": Path(argv[0]).name if argv else "",
        "exit_code": exit_code,
        # The load-bearing field for the v40 verdict-honesty gate: a
        # postmortem claiming tests_passing=true must have a test-run
        # record with passed=true. A timeout never counts as passed.
        "passed": (exit_code == 0) and not timed_out,
        "timed_out": bool(timed_out),
        "duration_ms": round(duration_ms, 3),
        "stdout_tail": _stdout_tail(stdout),
        "ts": round(time.time(), 3),
    }


def record_test_run(
    *,
    argv: list[str],
    exit_code: int | None,
    duration_ms: float,
    stdout: str = "",
    timed_out: bool = False,
    mind_dir: Path | str | None = None,
) -> Path | None:
    """Append one test-run record to the test-run ledger.

    Called from the shell tool for every pytest invocation. No-op
    (returns ``None``) when ``CHIMERA_SOAK_RUN_ID`` is unset or ``argv``
    is not a test command. Fail-soft: any error is swallowed.

    ``mind_dir`` defaults to :func:`default_mind_dir` because the shell
    handler has no ``config`` object to thread one through.
    """
    rid = soak_run_id()
    if not rid:
        return None
    if not is_test_command(argv):
        return None
    target = default_mind_dir() if mind_dir is None else mind_dir
    ledger_dir = soak_ledger_dir(target, rid)
    if ledger_dir is None:
        return None
    try:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        record = build_test_run_record(
            run_id=rid,
            argv=argv,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            timed_out=timed_out,
        )
        path = ledger_dir / TEST_RUNS_FILENAME
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return path
    except Exception:  # noqa: BLE001 - fail-soft by contract
        return None
