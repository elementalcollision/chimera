"""Tool subprocesses must not orphan when the call is cancelled.

The 2026-06-16 testing crashes were a memory leak: ACT's per-phase budget
wrapper (asyncio.wait_for) cancels the phase coroutine when a cycle runs long.
That cancellation propagates into a running ``shell``/``code_exec`` tool call as
CancelledError — which cancels the awaited ``proc.communicate()`` but does NOT
kill the OS process. The child (often a memory-heavy ``pytest``/``uv`` gate run)
orphaned, and across the many cycles a soak battery drives they accumulated and
exhausted memory.

These tests reproduce the cancellation and assert the child is dead. Without the
``finally: proc.kill()`` guard in the tools, ``proc.wait()`` below would block on
the still-running sleep and the ``wait_for`` would time out → test fails.
"""

from __future__ import annotations

import asyncio
import contextlib

from chimera.tools.code_exec import code_exec_handler
from chimera.tools.dispatch import DispatchContext
from chimera.tools.shell import shell_handler


def _assert_killed_on_cancel(monkeypatch, make_handler_coro):
    """Spawn a long-sleeping child via the handler, cancel mid-flight, and
    assert the OS process was killed (not orphaned)."""
    created: list = []
    real = asyncio.create_subprocess_exec

    async def capture(*a, **k):
        proc = await real(*a, **k)
        created.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)

    async def inner():
        task = asyncio.create_task(make_handler_coro())
        # Wait until the child is actually spawned.
        for _ in range(500):
            if created:
                break
            await asyncio.sleep(0.02)
        assert created, "tool never spawned a subprocess"
        proc = created[0]

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # If the fix is in place the child was killed → wait() returns promptly
        # with a signal-death returncode. If it orphaned, wait() blocks on the
        # 30s sleep and wait_for raises TimeoutError (test failure).
        await asyncio.wait_for(proc.wait(), timeout=10)
        assert proc.returncode is not None
        assert proc.returncode != 0  # killed by signal, not a clean exit

    asyncio.run(inner())


def test_code_exec_kills_child_on_cancel(monkeypatch):
    ctx = DispatchContext(elevated=True)
    _assert_killed_on_cancel(
        monkeypatch,
        lambda: code_exec_handler(
            {"code": "import time\ntime.sleep(30)", "timeout_s": 30}, ctx
        ),
    )


def test_shell_kills_child_on_cancel(monkeypatch):
    # python3 is on the shell allow-list; mirrors the real gate path
    # (shell → uv/pytest) without needing an elevated context.
    ctx = DispatchContext()
    _assert_killed_on_cancel(
        monkeypatch,
        lambda: shell_handler(
            {"argv": ["python3", "-c", "import time; time.sleep(30)"]}, ctx
        ),
    )
