"""Regression tests for :mod:`chimera._async_loop`.

The bug we're guarding against: ``asyncio.run`` invoked N times in
succession against an httpx-backed coroutine deadlocks at the start
of conv-42's first QA in the LoCoMo hybrid-retrieval batch (Python
3.14, anyio backend, shutdown_default_executor wedge). The fix is
to route every call through one persistent loop. These tests pin
that contract.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from chimera import _async_loop


@pytest.fixture(autouse=True)
def _reset_loop():
    _async_loop._reset_for_tests()
    yield
    _async_loop._reset_for_tests()


def test_runs_coroutine_and_returns_value() -> None:
    async def _coro() -> int:
        await asyncio.sleep(0)
        return 7

    assert _async_loop.run_on_persistent_loop(_coro()) == 7


def test_reuses_single_loop_across_many_calls() -> None:
    """The whole point of the helper — N calls, one loop.

    If a future regression reintroduces per-call ``asyncio.run``,
    each call would observe a fresh running-loop id and this assert
    flips. 50 iterations covers the conv-42 threshold (≈6 calls)
    with headroom.
    """
    loop_ids: set[int] = set()

    async def _capture() -> None:
        loop_ids.add(id(asyncio.get_running_loop()))

    for _ in range(50):
        _async_loop.run_on_persistent_loop(_capture())

    assert len(loop_ids) == 1


def test_runs_off_calling_thread() -> None:
    caller_thread = threading.get_ident()
    observed: dict[str, int] = {}

    async def _capture() -> None:
        observed["thread"] = threading.get_ident()

    _async_loop.run_on_persistent_loop(_capture())
    assert observed["thread"] != caller_thread


def test_exception_propagates() -> None:
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        _async_loop.run_on_persistent_loop(_boom())


def test_cli_call_sites_use_persistent_loop() -> None:
    """No surviving ``asyncio.run`` / ``_asyncio.run`` in eval-path
    CLI sites — only the legitimate long-running server entries
    (``serve_http`` / ``serve_stdio``) and docstring references
    are permitted.

    Guards against a sibling deadlock on the LoCoMo ingestion path
    (and any other in-loop CLI subcommand) introduced by repeated
    per-call ``asyncio.run`` invocations against httpx-backed
    coroutines (anyio backend, Python 3.14).
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for rel in ("chimera/cli.py", "chimera/core/loop.py"):
        lines = (repo / rel).read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            if "asyncio.run(" not in line and "_asyncio.run(" not in line:
                continue
            # Allowed: the two server entries that own the process loop
            # for their entire lifetime (no risk of repeated teardown).
            # Look at this line plus the next one to catch multi-line calls.
            window = line + "\n" + (lines[lineno] if lineno < len(lines) else "")
            if "serve_http" in window or "serve_stdio" in window:
                continue
            raise AssertionError(
                f"{rel}:{lineno} still uses asyncio.run — wrap with "
                f"run_on_persistent_loop instead.\n  {line.rstrip()}"
            )


def test_repeated_httpx_like_coroutines_do_not_wedge() -> None:
    """Sibling-defect repro: many successive submissions of a
    coroutine that uses asyncio's default executor (the surface
    that wedged on httpx+anyio at conv-42 and again at conv-26).

    Without the persistent loop, the shutdown_default_executor
    teardown step parks the main thread on a mutex after a handful
    of iterations. With the persistent loop, all N iterations
    complete promptly.
    """

    async def _exec_bound() -> int:
        loop = asyncio.get_running_loop()
        # run_in_executor with default executor — mirrors the anyio
        # backend's worker-thread offload pattern.
        return await loop.run_in_executor(None, lambda: 1)

    total = 0
    for _ in range(200):
        total += _async_loop.run_on_persistent_loop(_exec_bound())
    assert total == 200


def test_survives_concurrent_submissions() -> None:
    """Two threads submitting overlapping coroutines must both
    finish; the loop is shared and must not serialize on a flag.
    """
    results: list[int] = []
    results_lock = threading.Lock()

    async def _work(n: int) -> int:
        await asyncio.sleep(0.01)
        return n

    def _submit(n: int) -> None:
        v = _async_loop.run_on_persistent_loop(_work(n))
        with results_lock:
            results.append(v)

    threads = [threading.Thread(target=_submit, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()
    assert sorted(results) == list(range(8))
