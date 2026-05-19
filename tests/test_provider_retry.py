"""Tests for chimera.providers.retry (v3.5)."""

from __future__ import annotations

import httpx
import pytest

from chimera.providers.retry import is_transient, retry_call


def _make_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://x/")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"boom {code}", request=req, response=resp)


def test_classifier_transient_status_codes():
    for code in (408, 425, 429, 500, 502, 503, 504):
        assert is_transient(_make_status_error(code))


def test_classifier_permanent_status_codes():
    for code in (400, 401, 403, 404, 422, 501):
        assert not is_transient(_make_status_error(code))


def test_classifier_network_errors():
    assert is_transient(httpx.ConnectError("nope"))
    assert is_transient(httpx.ReadTimeout("slow"))
    assert is_transient(httpx.PoolTimeout("busy"))


def test_classifier_unknown_exceptions_are_permanent():
    assert not is_transient(ValueError("nope"))
    assert not is_transient(RuntimeError("nope"))


async def test_retry_succeeds_after_one_transient_failure():
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_status_error(503)
        return "ok"

    out = await retry_call(flaky, max_attempts=3, sleep=_no_sleep, rng=lambda: 0.5)
    assert out == "ok"
    assert calls["n"] == 2


async def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    async def always_503() -> str:
        calls["n"] += 1
        raise _make_status_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_call(always_503, max_attempts=3, sleep=_no_sleep, rng=lambda: 0.0)
    assert calls["n"] == 3


async def test_retry_does_not_retry_permanent_errors():
    calls = {"n": 0}

    async def perm_401() -> str:
        calls["n"] += 1
        raise _make_status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_call(perm_401, max_attempts=3, sleep=_no_sleep, rng=lambda: 0.0)
    assert calls["n"] == 1


async def _no_sleep(_delay: float) -> None:
    return None
