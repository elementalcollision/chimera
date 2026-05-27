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
