"""Tests for chimera.a2a.remote_sync (v3.7)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from chimera.a2a.remote_sync import (
    _entry_from_healthz,
    _parse_remote_urls,
    sweep_remote_stale,
    sync_remote_peers,
)


def test_parse_remote_urls_empty_returns_empty():
    assert _parse_remote_urls("") == []
    assert _parse_remote_urls(None) == []


def test_parse_remote_urls_strips_and_splits():
    raw = " http://a:1/ ,  http://b:2/ ,,http://c:3"
    assert _parse_remote_urls(raw) == ["http://a:1", "http://b:2", "http://c:3"]


def test_entry_from_healthz_builds_http_reach():
    e = _entry_from_healthz(
        "http://peer-a:8765",
        {"agent_id": "chimera@host-a", "version": "3.7.0", "capabilities": ["x", "y"]},
        token="tok-1",
    )
    assert e.agent_id == "chimera@host-a"
    assert e.version == "3.7.0"
    assert e.capabilities == ("x", "y")
    assert e.reach == {
        "transport": "http",
        "url": "http://peer-a:8765/mcp",
        "bearer": "tok-1",
    }


def test_sync_writes_entries_into_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_REGISTRY_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "version": "3.7.0",
                "agent_id": "chimera@peer-a",
                "capabilities": ["chimera.identity"],
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    class _FakeClient(real_client):  # type: ignore[misc]
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr("chimera.a2a.remote_sync.httpx.Client", _FakeClient)

    result = sync_remote_peers(["http://peer-a:8765"])
    assert result.fetched == 1
    assert result.added == 1
    assert result.failures == []

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["agent_id"] == "chimera@peer-a"
    assert body["reach"]["transport"] == "http"


def test_sync_records_failures_without_writing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_REGISTRY_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    transport = httpx.MockTransport(handler)

    class _FakeClient(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr("chimera.a2a.remote_sync.httpx.Client", _FakeClient)

    result = sync_remote_peers(["http://flaky:1"])
    assert result.fetched == 0
    assert len(result.failures) == 1
    assert list(tmp_path.glob("*.json")) == []


def test_sweep_remote_stale_removes_only_old_http_entries(tmp_path: Path):
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).isoformat()
    fresh_ts = dt.datetime.now(dt.timezone.utc).isoformat()
    (tmp_path / "old_http.json").write_text(json.dumps({
        "agent_id": "old", "version": "1", "capabilities": [],
        "pid": 0, "host": "a", "reach": {"transport": "http", "url": "x"},
        "registered_at": old_ts, "schema_version": 1,
    }))
    (tmp_path / "fresh_http.json").write_text(json.dumps({
        "agent_id": "fresh", "version": "1", "capabilities": [],
        "pid": 0, "host": "b", "reach": {"transport": "http", "url": "y"},
        "registered_at": fresh_ts, "schema_version": 1,
    }))
    (tmp_path / "old_stdio.json").write_text(json.dumps({
        "agent_id": "stdio", "version": "1", "capabilities": [],
        "pid": 12345, "host": "c", "reach": {"transport": "stdio"},
        "registered_at": old_ts, "schema_version": 1,
    }))

    n = sweep_remote_stale(max_age_hours=24.0, dir=tmp_path)
    assert n == 1
    remaining = {p.name for p in tmp_path.glob("*.json")}
    assert remaining == {"fresh_http.json", "old_stdio.json"}
