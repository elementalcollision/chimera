"""Retry-with-backoff for provider calls (ADR 0019, v3.5).

Wraps ``complete_with_tools`` and streaming runs with bounded exponential
backoff + jitter, retrying only on classifiable transient errors:

  - httpx connect / read / pool timeouts
  - httpx network errors
  - HTTP 408 / 425 / 429 / 5xx (except 501)
  - anthropic.APIConnectionError / .APITimeoutError / .RateLimitError /
    .InternalServerError

Permanent errors (401, 403, 404, 400, 422, anthropic.BadRequestError, …)
bubble immediately.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)


T = TypeVar("T")


_TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504, 522, 524}


def is_transient(exc: BaseException) -> bool:
    """Classify whether the exception is worth retrying."""
    # httpx
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.ConnectTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError,
                        httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_CODES
    # anthropic SDK — import lazily so tests don't require it installed.
    try:
        import anthropic
    except Exception:
        anthropic = None  # type: ignore[assignment]
    if anthropic is not None:
        if isinstance(
            exc,
            (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ),
        ):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            try:
                return exc.status_code in _TRANSIENT_HTTP_CODES
            except Exception:
                return False
    return False


async def retry_call(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    classify: Callable[[BaseException], bool] = is_transient,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Run ``fn()`` with exponential backoff + jitter on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except BaseException as exc:  # noqa: BLE001 — we re-raise non-transients
            if not classify(exc) or attempt == max_attempts:
                raise
            last_exc = exc
            backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = backoff * (0.5 + rng())  # ~0.5×–1.5× full jitter
            delay = min(max_delay, jitter)
            logger.warning(
                "provider retry %d/%d after %s; sleeping %.2fs",
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            await sleep(delay)
    # Unreachable — the final attempt either returns or raises.
    raise last_exc  # type: ignore[misc]
