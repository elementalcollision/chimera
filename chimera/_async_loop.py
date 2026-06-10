"""Persistent asyncio loop on a daemon thread.

Repeated ``asyncio.run(coro)`` calls deadlock on Python 3.14 when the
coroutine uses ``httpx.AsyncClient`` (or any anyio-backed async
resource): each call's loop-teardown invokes
``shutdown_default_executor``, which blocks on a worker thread whose
state was set up by an earlier loop. After a handful of cycles the
executor wedges — main thread parked in ``kevent``, worker parked on
``SimpleQueue.get`` — and the process hangs at 0% CPU.

LoCoMo's hybrid-retrieval batch trips this at the boundary between
conversations because each question incurs an ``asyncio.run`` cycle
through the OpenRouter provider. Bisected reproducer is the 4-conv
slice in
``mind/research/f2-blocked-by-hybrid-retrieval-deadlock-2026-05-27.md``.

This module exposes :func:`run_on_persistent_loop`, which submits each
coroutine to a single event loop running on a daemon background
thread. Teardown is deferred to process exit, so the
``shutdown_default_executor`` path never fires mid-batch.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, TypeVar

T = TypeVar("T")


_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _runner() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        threading.Thread(
            target=_runner, name="chimera-async-loop", daemon=True
        ).start()
        ready.wait()
        _loop = loop
        return loop


def run_on_persistent_loop(coro: Awaitable[T]) -> T:
    """Run ``coro`` to completion on the shared background loop.

    Blocks the calling thread until the coroutine resolves. Re-raises
    any exception from inside the coroutine. Safe to call from any
    non-loop thread; never call from inside the loop itself.
    """
    loop = _get_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


def _reset_for_tests() -> None:
    """Tear down the loop (tests only)."""
    global _loop
    with _lock:
        if _loop is None:
            return
        loop = _loop
        _loop = None
    loop.call_soon_threadsafe(loop.stop)
