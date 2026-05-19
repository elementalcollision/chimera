"""SIGTERM/SIGINT → asyncio.Event drain pattern.

Ported from ``village/libs/village_drain`` per pillar-positioning.md
Pattern 3.

Signal handlers ONLY flip an event flag — no blocking work, no DB calls.
Async code observes the event and exits its inner loop gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import signal as _signal
from typing import Iterable

logger = logging.getLogger(__name__)


def install_drain_handlers(
    drain_event: asyncio.Event,
    *,
    service_name: str = "chimera",
    signals: Iterable[int] = (_signal.SIGTERM, _signal.SIGINT),
) -> None:
    """Register signal handlers that set ``drain_event``.

    Idempotent on the same event loop. Silently no-ops on platforms that
    don't support ``loop.add_signal_handler`` (Windows).
    """
    loop = asyncio.get_running_loop()

    def _handler(sig_num: int) -> None:
        if drain_event.is_set():
            logger.debug("%s: ignoring repeat signal %s", service_name, sig_num)
            return
        try:
            name = _signal.Signals(sig_num).name
        except (ValueError, AttributeError):
            name = str(sig_num)
        logger.info("%s: received %s; draining", service_name, name)
        drain_event.set()

    for sig in signals:
        try:
            loop.add_signal_handler(sig, _handler, sig)
        except (NotImplementedError, RuntimeError):
            # Windows or restricted env; not fatal.
            logger.debug("%s: signal %s not installable; skipping", service_name, sig)


async def drain_and_wait(
    drain_event: asyncio.Event,
    *,
    timeout: float = 30.0,
) -> bool:
    """Wait up to ``timeout`` seconds for the drain event to fire.

    Returns ``True`` if drained within the window, ``False`` on timeout.
    """
    try:
        await asyncio.wait_for(drain_event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
